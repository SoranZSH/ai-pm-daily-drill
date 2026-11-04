package main

// 第二阶段：按选定的导入模式生成变更方案——定位分类、分配题号、改写前置、校验前置关系。

import (
	"encoding/json"
	"fmt"
	"sort"
	"strings"
)

type entry struct {
	ID, Ref, Level, Q string
}

type catPlan struct {
	cat      *category
	isNew    bool
	mode     string
	before   int
	added    []entry
	replaced []entry
	removed  []entry
	newF     int
	newX     int
}

type plan struct {
	mode        string // incremental / overwrite
	cats        []*catPlan
	final       []*category // 导入后的完整题库
	removedCats []*category // 覆盖模式下被删除的旧分类
	refToID     map[string]string
	refTitle    map[string]string
	beforeTotal int
}

func buildPlan(pu *parsedUpdate, bank []*category, mode string, reg *registry, today string) (*plan, []string, []string) {
	var warns, errs []string
	p := &plan{mode: mode, refToID: map[string]string{}, refTitle: map[string]string{}}
	for _, c := range bank {
		p.beforeTotal += len(c.Items)
	}

	// 起点：增量 = 现有题库副本；覆盖 = 空
	finalByFile := map[string]*category{}
	var order []string
	if mode == "incremental" {
		for _, c := range bank {
			cp := *c
			cp.Items = append([]json.RawMessage(nil), c.Items...)
			cp.IDs = append([]string(nil), c.IDs...)
			finalByFile[c.File] = &cp
			order = append(order, c.File)
		}
	} else {
		p.removedCats = bank
	}
	bankByFile := map[string]*category{}
	bankByName := map[string]*category{}
	for _, c := range bank {
		bankByFile[c.File] = c
		bankByName[c.Category] = c
	}
	reg.observe(allIDs(bank)) // 旧题号（含覆盖模式下将删除的）全部计入，保证永不复用

	// ── A. 定位分类、分配题号 ──
	type pending struct {
		cp    *catPlan
		uc    updateCat
		items []parsedItem
		del   map[string]bool
	}
	var pend []pending
	touched := map[string]bool{}
	deleted := map[string]bool{}
	for ci, uc := range pu.file.Categories {
		where := catLabel(ci, uc)
		items := pu.items[ci]
		var target *category
		isNew := false
		if mode == "incremental" {
			if uc.File != "" {
				target = finalByFile[uc.File]
			} else if c := bankByName[uc.Category]; c != nil {
				target = finalByFile[c.File]
			}
		}
		if target == nil {
			isNew = true
			if uc.File == "" || uc.Category == "" || uc.CategoryEn == "" || uc.Domain == "" {
				if mode == "overwrite" {
					errs = append(errs, fmt.Sprintf("%s：题库覆盖时每个分类都要写全 file / category / category_en / domain", where))
				} else {
					errs = append(errs, fmt.Sprintf("%s：找不到现有分类；新建分类需写全 file / category / category_en / domain", where))
				}
				continue
			}
			if !fileNameRe.MatchString(uc.File) {
				errs = append(errs, fmt.Sprintf("%s：分类文件名「%s」格式应为 两位序号_英文小写.json，如 04_agents.json", where, uc.File))
				continue
			}
			if !domainRe.MatchString(uc.Domain) {
				errs = append(errs, fmt.Sprintf("%s：domain「%s」应为 2–4 个大写字母", where, uc.Domain))
				continue
			}
			target = &category{File: uc.File, Category: uc.Category, CategoryEn: uc.CategoryEn, Domain: uc.Domain, CRLF: true}
			if old := bankByFile[uc.File]; old != nil {
				target.CRLF = old.CRLF
			}
		} else if uc.Domain != "" && target.Domain != "" && uc.Domain != target.Domain {
			warns = append(warns, fmt.Sprintf("%s：domain 写的是 %s，以现有分类的 %s 为准", where, uc.Domain, target.Domain))
		}
		if touched[target.File] {
			errs = append(errs, fmt.Sprintf("%s：同一个分类在文件里出现了两次，请合并成一个", where))
			continue
		}
		touched[target.File] = true

		cmode := strings.ToLower(strings.TrimSpace(uc.Mode))
		if cmode == "" {
			cmode = "merge"
		}
		if cmode != "merge" && cmode != "replace" {
			errs = append(errs, fmt.Sprintf("%s：mode 只能是 merge 或 replace", where))
			continue
		}
		if mode == "overwrite" {
			cmode = "replace"
			if len(uc.DeleteIDs) > 0 {
				errs = append(errs, fmt.Sprintf("%s：题库覆盖模式下不能写 delete_ids（覆盖会删除全部旧题）", where))
			}
		}
		if len(items) == 0 && len(uc.DeleteIDs) == 0 {
			errs = append(errs, fmt.Sprintf("%s：既没有 items 也没有 delete_ids（用不到的话把这整块删掉）", where))
			continue
		}
		cp := &catPlan{cat: target, isNew: isNew, mode: cmode, before: len(target.Items)}
		if isNew && mode == "incremental" && bankByFile[uc.File] != nil {
			cp.isNew = false
		}

		hasRefs := false
		for _, it := range items {
			if it.info.Ref != "" {
				hasRefs = true
			}
		}
		if hasRefs && target.Domain == "" {
			errs = append(errs, fmt.Sprintf("%s：这是旧版分类（没有 domain），不能再加新题；请新建分类或使用题库覆盖", where))
			continue
		}
		del := map[string]bool{}
		for _, id := range uc.DeleteIDs {
			if mode == "overwrite" {
				break
			}
			if !contains(target.IDs, id) {
				errs = append(errs, fmt.Sprintf("%s：delete_ids 里的 %s 在这个分类里不存在", where, id))
				continue
			}
			del[id] = true
			deleted[id] = true
		}
		for _, it := range items {
			if it.obj == nil {
				continue
			}
			if it.info.Ref != "" && refRe.MatchString(it.info.Ref) && (it.info.Level == "F" || it.info.Level == "X") && target.Domain != "" {
				id := reg.next(target.Domain, it.info.Level)
				p.refToID[it.info.Ref] = id
				p.refTitle[it.info.Ref] = it.info.QCn
			}
			if it.info.ID != "" {
				if mode == "overwrite" {
					errs = append(errs, it.label+"：题库覆盖模式下只能写新题（ref），不能改已有题（id）")
				} else if !contains(target.IDs, it.info.ID) {
					errs = append(errs, it.label+"：要修改的题号在这个分类里不存在")
				} else if del[it.info.ID] {
					errs = append(errs, it.label+"：同时出现在 items 和 delete_ids 里")
				}
			}
		}
		pend = append(pend, pending{cp: cp, uc: uc, items: items, del: del})
	}
	if len(errs) > 0 {
		return nil, warns, errs
	}

	// ── B. 组装分类内容 ──
	for _, pd := range pend {
		cp, target := pd.cp, pd.cp.cat
		oldItems := map[string]json.RawMessage{}
		for i, id := range target.IDs {
			oldItems[id] = target.Items[i]
		}
		var newItems []json.RawMessage
		edited := map[string]json.RawMessage{}
		for _, it := range pd.items {
			o := append(object(nil), it.obj...)
			o.set("prereq", jsonStrings(resolvePrereq(it.info.Prereq, p.refToID)))
			if it.info.Ref != "" {
				id := p.refToID[it.info.Ref]
				o.rename("ref", "id", jsonString(id))
				o.set("added", jsonString(today))
				newItems = append(newItems, o.marshal())
				cp.added = append(cp.added, entry{ID: id, Ref: it.info.Ref, Level: it.info.Level, Q: it.info.QCn})
				if it.info.Level == "F" {
					cp.newF++
				} else {
					cp.newX++
				}
			} else {
				added := infoOf(oldItems[it.info.ID]).Added
				if added == "" {
					added = today
				}
				o.set("added", jsonString(added))
				edited[it.info.ID] = o.marshal()
				cp.replaced = append(cp.replaced, entry{ID: it.info.ID, Level: it.info.Level, Q: it.info.QCn})
			}
		}
		var kept []json.RawMessage
		for i, id := range target.IDs {
			raw := target.Items[i]
			switch {
			case pd.del[id]:
				cp.removed = append(cp.removed, entry{ID: id, Level: levelOfID(id), Q: infoOf(raw).QCn})
			case edited[id] != nil:
				kept = append(kept, edited[id])
			case cp.mode == "replace":
				cp.removed = append(cp.removed, entry{ID: id, Level: levelOfID(id), Q: infoOf(raw).QCn})
			default:
				kept = append(kept, raw)
			}
		}
		all := append(kept, newItems...)
		sort.SliceStable(all, func(i, j int) bool { return idLess(infoOf(all[i]).ID, infoOf(all[j]).ID) })
		target.Items = all
		target.IDs = nil
		for _, r := range all {
			target.IDs = append(target.IDs, infoOf(r).ID)
		}
		if len(target.Items) == 0 {
			errs = append(errs, fmt.Sprintf("%s：操作后这个分类会变成空的", target.File))
		}
		if _, ok := finalByFile[target.File]; !ok {
			finalByFile[target.File] = target
			order = append(order, target.File)
		}
		p.cats = append(p.cats, cp)
	}

	// ── C. 前置关系与领域校验（基于导入后的完整题库） ──
	sort.Strings(order)
	infos := map[string]itemInfo{}
	domainOwner := map[string]string{}
	for _, f := range order {
		c := finalByFile[f]
		p.final = append(p.final, c)
		if c.Domain != "" {
			if o, ok := domainOwner[c.Domain]; ok {
				errs = append(errs, fmt.Sprintf("领域前缀 %s 同时被 %s 和 %s 使用", c.Domain, o, c.File))
			}
			domainOwner[c.Domain] = c.File
		}
		for _, r := range c.Items {
			it := infoOf(r)
			infos[it.ID] = it
		}
	}
	labelOf := map[string]string{}
	for ci := range pu.file.Categories {
		for _, it := range pu.items[ci] {
			id := it.info.ID
			if it.info.Ref != "" {
				id = p.refToID[it.info.Ref]
			}
			labelOf[id] = it.label
		}
	}
	for ci := range pu.file.Categories {
		for _, it := range pu.items[ci] {
			if it.obj == nil {
				continue
			}
			hasF, unresolved := false, false
			for _, pre := range it.info.Prereq {
				var target string
				if refRe.MatchString(pre) {
					id, ok := p.refToID[pre]
					if !ok {
						errs = append(errs, fmt.Sprintf("%s：前置 %s 在本文件里不存在", it.label, pre))
						unresolved = true
						continue
					}
					target = id
				} else {
					target = pre
					if _, ok := infos[target]; !ok {
						switch {
						case deleted[target]:
							errs = append(errs, fmt.Sprintf("%s：前置 %s 是本文件 delete_ids 中要删除的题", it.label, pre))
						case mode == "overwrite" && contains(allIDs(bank), target):
							errs = append(errs, fmt.Sprintf("%s：前置 %s 是旧题库的题，题库覆盖后将不存在", it.label, pre))
						default:
							errs = append(errs, fmt.Sprintf("%s：前置题号 %s 在题库里不存在", it.label, pre))
						}
						unresolved = true
						continue
					}
				}
				if levelOfID(target) == "F" {
					hasF = true
				}
				if d := domainOf(target); d != "" && infos[target].ID != "" {
					self := it.info.ID
					if it.info.Ref != "" {
						self = p.refToID[it.info.Ref]
					}
					if domainOf(self) != "" && domainOf(self) != d {
						warns = append(warns, fmt.Sprintf("%s：前置题 %s 跨了领域（可以，但请确认确实需要）", it.label, target))
					}
				}
			}
			if it.info.Level == "X" && len(it.info.Prereq) > 0 && !hasF && !unresolved {
				errs = append(errs, fmt.Sprintf("%s：拓展题的前置里至少要有 1 道基础题（F）", it.label))
			}
		}
	}
	// 题库里原有题目的前置若被本次删除，也要拦下
	for id, it := range infos {
		if _, isNew := labelOf[id]; isNew {
			continue
		}
		for _, pre := range it.Prereq {
			if _, ok := infos[pre]; !ok {
				errs = append(errs, fmt.Sprintf("现有题 %s 以 %s 为前置，但 %s 将被删除；请同时修改或删除 %s", id, pre, pre, id))
			}
		}
	}
	if cyc := findCycle(infos); cyc != "" {
		errs = append(errs, "前置关系出现循环："+cyc)
	}
	return p, warns, errs
}

func resolvePrereq(pre []string, refToID map[string]string) []string {
	out := make([]string, 0, len(pre))
	seen := map[string]bool{}
	for _, x := range pre {
		if id, ok := refToID[x]; ok {
			x = id
		}
		if !seen[x] {
			out = append(out, x)
			seen[x] = true
		}
	}
	return out
}

func domainOf(id string) string {
	if m := idV2Re.FindStringSubmatch(id); m != nil {
		return m[1]
	}
	return ""
}

// findCycle 返回一条循环路径（如 "A → B → A"），没有循环返回空串
func findCycle(infos map[string]itemInfo) string {
	const (
		white = 0
		gray  = 1
		black = 2
	)
	color := map[string]int{}
	var stack []string
	var found string
	var visit func(string) bool
	visit = func(id string) bool {
		color[id] = gray
		stack = append(stack, id)
		for _, p := range infos[id].Prereq {
			if _, ok := infos[p]; !ok {
				continue
			}
			if color[p] == gray {
				i := len(stack) - 1
				for i >= 0 && stack[i] != p {
					i--
				}
				found = strings.Join(append(append([]string{}, stack[i:]...), p), " → ")
				return true
			}
			if color[p] == white && visit(p) {
				return true
			}
		}
		stack = stack[:len(stack)-1]
		color[id] = black
		return false
	}
	ids := make([]string, 0, len(infos))
	for id := range infos {
		ids = append(ids, id)
	}
	sort.Strings(ids)
	for _, id := range ids {
		if color[id] == white && visit(id) {
			return found
		}
	}
	return ""
}

func allIDs(cats []*category) []string {
	var out []string
	for _, c := range cats {
		out = append(out, c.IDs...)
	}
	return out
}
