package main

// 第一阶段：解析更新文件（契约① v2），做与导入模式无关的逐题校验。

import (
	"bytes"
	"encoding/json"
	"fmt"
	"os"
	"regexp"
	"strings"
)

const formatV2 = "interview-bank-update/v2"

var (
	refRe        = regexp.MustCompile(`^N\d{1,3}$`)
	domainRe     = regexp.MustCompile(`^[A-Z]{2,4}$`)
	fileNameRe   = regexp.MustCompile(`^\d{2}_[a-z0-9_]+\.json$`)
	conceptKeyRe = regexp.MustCompile(`^[a-z]{2,4}\.[a-z0-9_]+$`)
	repoRe       = regexp.MustCompile(`^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$`)
	placeholder  = []string{"【", "】", "TODO", "待填", "XXX", "示例题目", "（在这里"}
	difficulties = map[string]bool{"基础": true, "中等": true, "较难": true}
	kinds        = map[string]bool{"knowledge": true, "idea": true, "method": true, "case": true}
	knownFields  = map[string]bool{"id": true, "ref": true, "level": true, "kind": true, "difficulty": true,
		"tags": true, "concepts": true, "prereq": true, "q_cn": true, "q_en": true, "concept": true,
		"a_en": true, "a_cn": true, "key_phrases": true, "approach": true, "tips": true,
		"source_repos": true, "added": true,
		"gist": true, "points": true, "a_pairs": true, "basics": true, "pitfalls": true, "walkthrough": true, "method": true}
)

type updateFile struct {
	Format     string      `json:"format"`
	BankMode   string      `json:"bank_mode"`
	Categories []updateCat `json:"categories"`
}

type updateCat struct {
	File       string            `json:"file"`
	Category   string            `json:"category"`
	CategoryEn string            `json:"category_en"`
	Domain     string            `json:"domain"`
	Mode       string            `json:"mode"`
	Items      []json.RawMessage `json:"items"`
	DeleteIDs  []string          `json:"delete_ids"`
}

type parsedItem struct {
	obj   object
	info  itemInfo
	label string
}

type parsedUpdate struct {
	path  string
	file  updateFile
	items [][]parsedItem // 与 file.Categories 一一对应
	refs  map[string]bool
}

func parseUpdate(path string, conceptMap map[string]conceptEntry) (*parsedUpdate, []string, []string) {
	var warns, errs []string
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, nil, []string{err.Error()}
	}
	data = bytes.TrimPrefix(data, []byte("\xef\xbb\xbf"))
	pu := &parsedUpdate{path: path, refs: map[string]bool{}}
	if err := json.Unmarshal(data, &pu.file); err != nil {
		return nil, nil, []string{"JSON 格式错误：" + describeJSONErr(data, err)}
	}
	if pu.file.Format != formatV2 {
		return nil, nil, []string{fmt.Sprintf("format 应为 %s（现在是「%s」）。旧格式已停用，请按 题库模板\\题库更新_模板.json 重写", formatV2, pu.file.Format)}
	}
	if m := pu.file.BankMode; m != "" && m != "incremental" && m != "overwrite" {
		errs = append(errs, fmt.Sprintf("bank_mode 只能是 incremental 或 overwrite，现在是「%s」", m))
	}
	if len(pu.file.Categories) == 0 {
		return nil, nil, []string{"文件里没有 categories（或为空）"}
	}

	for ci, uc := range pu.file.Categories {
		where := catLabel(ci, uc)
		var list []parsedItem
		for ii, raw := range uc.Items {
			obj, err := parseObject(raw)
			if err != nil {
				errs = append(errs, fmt.Sprintf("%s 第 %d 题：不是合法的 JSON 对象：%v", where, ii+1, err))
				list = append(list, parsedItem{})
				continue
			}
			it := infoOf(raw)
			label := fmt.Sprintf("%s 第 %d 题", where, ii+1)
			if it.Ref != "" {
				label = fmt.Sprintf("%s %s", where, it.Ref)
			} else if it.ID != "" {
				label = fmt.Sprintf("%s %s", where, it.ID)
			}
			ws, es := validateItem(obj, raw, it, conceptMap)
			for _, w := range ws {
				warns = append(warns, label+"："+w)
			}
			for _, e := range es {
				errs = append(errs, label+"："+e)
			}
			if it.Ref != "" && refRe.MatchString(it.Ref) {
				if pu.refs[it.Ref] {
					errs = append(errs, label+"：临时编号在文件里重复了")
				}
				pu.refs[it.Ref] = true
			}
			list = append(list, parsedItem{obj: obj, info: it, label: label})
		}
		pu.items = append(pu.items, list)
	}
	return pu, warns, errs
}

func catLabel(ci int, uc updateCat) string {
	switch {
	case uc.Category != "" && uc.File != "":
		return fmt.Sprintf("%s（%s）", uc.Category, uc.File)
	case uc.File != "":
		return uc.File
	case uc.Category != "":
		return uc.Category
	}
	return fmt.Sprintf("第 %d 个分类", ci+1)
}

func validateItem(obj object, raw json.RawMessage, it itemInfo, conceptMap map[string]conceptEntry) ([]string, []string) {
	var warns, errs []string
	// 字段类型
	var strict struct {
		Tags        []string    `json:"tags"`
		Concepts    []string    `json:"concepts"`
		Prereq      []string    `json:"prereq"`
		KeyPhrases  []bilingual `json:"key_phrases"`
		Concept     *bilingual  `json:"concept"`
		SourceRepos []string    `json:"source_repos"`
	}
	if err := json.Unmarshal(raw, &strict); err != nil {
		errs = append(errs, "字段类型不对："+err.Error())
	}
	for _, p := range obj {
		if !knownFields[p.k] {
			warns = append(warns, fmt.Sprintf("未知字段「%s」会原样保留，但程序不会使用它", p.k))
		}
	}

	// 编号：新题写 ref，改题写 id
	hasRef, hasID := obj.has("ref"), obj.has("id")
	switch {
	case hasRef && hasID:
		errs = append(errs, "ref 和 id 只能写一个：新题写 ref（N1、N2…），改已有题写 id")
	case !hasRef && !hasID:
		errs = append(errs, "缺少编号：新题写 ref（N1、N2…），改已有题写 id")
	case hasRef && !refRe.MatchString(it.Ref):
		errs = append(errs, fmt.Sprintf("临时编号「%s」格式应为 N 加数字，如 N1、N12", it.Ref))
	case hasID && !idV2Re.MatchString(it.ID):
		errs = append(errs, fmt.Sprintf("题号「%s」不是新格式（如 AGT-F001）。旧格式题目不能修改，请用题库覆盖替换", it.ID))
	}
	if obj.has("added") {
		warns = append(warns, "added 由导入工具自动填写，文件里的值会被忽略")
	}

	// 层级、题型、难度
	if it.Level != "F" && it.Level != "X" {
		errs = append(errs, fmt.Sprintf("level 只能是 F（基础）或 X（拓展），现在是「%s」", it.Level))
	} else if hasID && idV2Re.MatchString(it.ID) && levelOfID(it.ID) != it.Level {
		errs = append(errs, fmt.Sprintf("level 是 %s，但题号 %s 表示 %s 层级；层级不能通过改题变更", it.Level, it.ID, levelOfID(it.ID)))
	}
	if !kinds[it.Kind] {
		errs = append(errs, fmt.Sprintf("kind 只能是 knowledge / idea / method / case，现在是「%s」", it.Kind))
	}
	if !difficulties[it.Difficulty] {
		errs = append(errs, fmt.Sprintf("difficulty 只能是 基础 / 中等 / 较难，现在是「%s」", it.Difficulty))
	}
	if len(it.Tags) == 0 {
		errs = append(errs, "tags 至少一个")
	} else if len(it.Tags) > 3 {
		warns = append(warns, fmt.Sprintf("tags 有 %d 个，建议 1–3 个", len(it.Tags)))
	}

	// 概念键
	if len(it.Concepts) == 0 {
		errs = append(errs, "concepts 至少写 1 个概念键（见 知识地图.json）")
	} else if len(it.Concepts) > 3 {
		warns = append(warns, fmt.Sprintf("concepts 有 %d 个，建议 1–3 个", len(it.Concepts)))
	}
	var unknown []string
	for _, k := range it.Concepts {
		if !conceptKeyRe.MatchString(k) {
			errs = append(errs, fmt.Sprintf("概念键「%s」格式应为 小写领域.小写下划线名，如 rag.embedding", k))
		} else if conceptMap != nil {
			if _, ok := conceptMap[k]; !ok {
				unknown = append(unknown, k)
			}
		}
	}
	if len(unknown) > 0 {
		warns = append(warns, "知识地图里没有这些概念："+strings.Join(unknown, "、")+"（确认后可加进 知识地图.json）")
	}

	// 前置
	if !obj.has("prereq") {
		errs = append(errs, "缺少 prereq（基础题没有前置时写空数组 []）")
	} else if it.Level == "X" && len(it.Prereq) == 0 {
		errs = append(errs, "拓展题（X）必须至少有 1 道前置题，且其中至少 1 道是基础题（F）")
	}
	selfRef := it.Ref
	if selfRef == "" {
		selfRef = it.ID
	}
	seen := map[string]bool{}
	for _, p := range it.Prereq {
		if p == selfRef && p != "" {
			errs = append(errs, "前置题不能是自己")
		}
		if seen[p] {
			warns = append(warns, fmt.Sprintf("前置题 %s 写了两次", p))
		}
		seen[p] = true
		if !refRe.MatchString(p) && !idV2Re.MatchString(p) && !idLegacyRe.MatchString(p) {
			errs = append(errs, fmt.Sprintf("前置「%s」既不是临时编号（N1）也不是题号（AGT-F001）", p))
		}
	}

	// 正文
	for name, v := range map[string]string{"q_cn": it.QCn, "q_en": it.QEn, "a_en": it.AEn,
		"a_cn": it.ACn, "approach": it.Approach, "tips": it.Tips} {
		if strings.TrimSpace(v) == "" {
			errs = append(errs, name+" 不能为空")
		}
	}
	if it.Concept == nil {
		errs = append(errs, "缺少 concept（概念解析，中英文各一段）")
	} else if strings.TrimSpace(it.Concept.Cn) == "" || strings.TrimSpace(it.Concept.En) == "" {
		errs = append(errs, "concept 的 cn / en 都要写")
	}
	if len(it.KeyPhrases) < 2 {
		errs = append(errs, "key_phrases 至少 2 条（建议 4–5 条）")
	} else if len(it.KeyPhrases) < 4 || len(it.KeyPhrases) > 5 {
		warns = append(warns, fmt.Sprintf("key_phrases 有 %d 条，建议 4–5 条", len(it.KeyPhrases)))
	}
	for i, kp := range it.KeyPhrases {
		if strings.TrimSpace(kp.En) == "" || strings.TrimSpace(kp.Cn) == "" {
			errs = append(errs, fmt.Sprintf("key_phrases 第 %d 条的 en / cn 不能为空", i+1))
		}
	}

	// 来源仓库
	for _, r := range it.SourceRepos {
		if !repoRe.MatchString(r) {
			warns = append(warns, fmt.Sprintf("source_repos 里的「%s」不是 owner/name 格式", r))
		}
		if it.Kind != "case" {
			name := r
			if i := strings.Index(r, "/"); i >= 0 {
				name = r[i+1:]
			}
			lq := strings.ToLower(it.QCn + " " + it.QEn)
			if len(name) >= 3 && (strings.Contains(lq, strings.ToLower(r)) || strings.Contains(lq, strings.ToLower(name))) {
				warns = append(warns, fmt.Sprintf("题目里出现了仓库名「%s」；只有 kind=case 的题可以点名具体项目", name))
			}
		}
	}

	// 模板占位
	for _, ph := range placeholder {
		if strings.Contains(string(raw), ph) {
			errs = append(errs, fmt.Sprintf("还有模板占位内容（含「%s」），请替换成正式内容", ph))
			break
		}
	}

	// 质量提醒
	if n := len(strings.Fields(it.AEn)); it.AEn != "" && (n < 120 || n > 200) {
		warns = append(warns, fmt.Sprintf("英文答案 %d 词；60–90 秒口述约 120–200 词", n))
	}
	if n := len([]rune(it.ACn)); it.ACn != "" && n < 150 {
		warns = append(warns, fmt.Sprintf("中文对照只有 %d 字，可能没有逐句对照", n))
	}
	if q := strings.TrimSpace(it.QEn); q != "" && !strings.HasSuffix(q, "?") && !strings.HasSuffix(q, ".") {
		warns = append(warns, "英文题目末尾没有问号/句号")
	}
	if strings.ContainsAny(it.AEn, "，。；：“”") {
		warns = append(warns, "英文答案里混入了中文标点")
	}

	// 规范 v2.1 新增字段
	w21, e21 := validateV21(obj, raw, it)
	warns = append(warns, w21...)
	errs = append(errs, e21...)
	return warns, errs
}
