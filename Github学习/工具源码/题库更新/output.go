package main

// 预览、概览、题库目录、题号对照表。

import (
	"bytes"
	"encoding/json"
	"fmt"
	"os"
	"sort"
	"strings"
)

type conceptEntry struct {
	Name    string   `json:"name"`
	Domain  string   `json:"domain"`
	Aliases []string `json:"aliases"`
}

func loadConceptMap(path string) map[string]conceptEntry {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil
	}
	var m struct {
		Concepts map[string]conceptEntry `json:"concepts"`
	}
	if json.Unmarshal(bytes.TrimPrefix(data, []byte("\xef\xbb\xbf")), &m) != nil {
		fmt.Println("  ⚠ 知识地图.json 格式不对，已跳过概念检查")
		return nil
	}
	return m.Concepts
}

func printPlan(p *plan) {
	section("📋 本次变更预览")
	after := 0
	for _, c := range p.final {
		after += len(c.Items)
	}
	if p.mode == "overwrite" {
		fmt.Println("\n  模式：【题库覆盖】")
		if len(p.removedCats) > 0 {
			fmt.Println("\n  将删除现有分类（已自动备份）：")
			for _, c := range p.removedCats {
				fmt.Printf("    － %s（%s）%d 题\n", c.Category, c.File, len(c.Items))
			}
		}
		fmt.Println("\n  将写入新分类：")
		for _, cp := range p.cats {
			fmt.Printf("    ＋ %s（%s，%s）基础 %d 道 + 拓展 %d 道\n", cp.cat.Category, cp.cat.File, cp.cat.Domain, cp.newF, cp.newX)
			for _, e := range cp.added {
				fmt.Printf("        %-9s ← %-4s [%s] %s\n", e.ID, e.Ref, e.Level, clip(e.Q, 36))
			}
		}
		fmt.Println("\n  ⚠ 每日一题的学习天数等记录会保留；旧题号的复习记录随旧题失效；新题号不会与任何旧题号重复。")
	} else {
		fmt.Println("\n  模式：【增量添加】")
		totalF, totalX := 0, 0
		for _, cp := range p.cats {
			tag := "修改"
			if cp.isNew {
				tag = "新建分类"
			} else if cp.mode == "replace" {
				tag = "整类替换"
			}
			fmt.Printf("\n  【%s】%s（%s）%d → %d 题\n", tag, cp.cat.Category, cp.cat.File, cp.before, len(cp.cat.Items))
			for _, e := range cp.added {
				fmt.Printf("    ＋ %-9s ← %-4s [%s] %s\n", e.ID, e.Ref, e.Level, clip(e.Q, 36))
			}
			for _, e := range cp.replaced {
				fmt.Printf("    ↻ %-9s        [%s] %s\n", e.ID, e.Level, clip(e.Q, 36))
			}
			for _, e := range cp.removed {
				fmt.Printf("    － %-9s        [%s] %s\n", e.ID, e.Level, clip(e.Q, 36))
			}
			totalF += cp.newF
			totalX += cp.newX
		}
		fmt.Printf("\n  本次新增：基础题 %d 道、拓展题 %d 道\n", totalF, totalX)
	}
	fmt.Printf("  题库总量：%d → %d 题\n", p.beforeTotal, after)
}

func printOverview(bank []*category) {
	section("现有题库概览")
	total := 0
	for _, c := range bank {
		f, x, legacy := 0, 0, 0
		for _, id := range c.IDs {
			switch {
			case idV2Re.MatchString(id) && levelOfID(id) == "F":
				f++
			case idV2Re.MatchString(id):
				x++
			default:
				legacy++
			}
		}
		total += len(c.Items)
		d := c.Domain
		if d == "" {
			d = "旧版"
		}
		line := fmt.Sprintf("  %-5s %4d 题  基础 %d / 拓展 %d", d, len(c.Items), f, x)
		if legacy > 0 {
			line += fmt.Sprintf(" / 旧格式 %d", legacy)
		}
		fmt.Printf("%s   %s（%s）\n", line, c.Category, c.File)
	}
	fmt.Printf("  合计 %d 题\n", total)
}

// writeCatalog 生成 题库目录.md：给出题的 AI 看现有题目，方便挂前置
func writeCatalog(path string, cats []*category, concepts map[string]conceptEntry) error {
	var b strings.Builder
	b.WriteString("# 题库目录\n\n")
	b.WriteString("> 由 题库更新.exe 自动生成，请勿手改。出题时把本文件发给 AI，用于选择前置题（prereq）和避免重复。\n\n")
	covered := map[string]bool{}
	total := 0
	for _, c := range cats {
		total += len(c.Items)
	}
	fmt.Fprintf(&b, "共 %d 个分类、%d 题。层级：F = 基础，X = 拓展（必须有基础题前置）。\n", len(cats), total)
	for _, c := range cats {
		d := c.Domain
		if d == "" {
			d = "旧版分类"
		}
		fmt.Fprintf(&b, "\n## %s（%s，%s）\n\n", c.Category, c.File, d)
		b.WriteString("| 题号 | 层级 | 题型 | 概念 | 前置 | 题目 |\n|---|---|---|---|---|---|\n")
		for _, raw := range c.Items {
			it := infoOf(raw)
			for _, k := range it.Concepts {
				covered[k] = true
			}
			lv, kind := it.Level, it.Kind
			if lv == "" {
				lv = "–"
			}
			if kind == "" {
				kind = "–"
			}
			pre := strings.Join(it.Prereq, ", ")
			if pre == "" {
				pre = "–"
			}
			con := strings.Join(it.Concepts, ", ")
			if con == "" {
				con = "–"
			}
			fmt.Fprintf(&b, "| %s | %s | %s | %s | %s | %s |\n", it.ID, lv, kind, con, pre, mdCell(it.QCn))
		}
	}
	if concepts != nil {
		var missing []string
		for k := range concepts {
			if !covered[k] {
				missing = append(missing, k)
			}
		}
		sort.Strings(missing)
		b.WriteString("\n## 知识地图中尚无题目覆盖的概念\n\n")
		if len(missing) == 0 {
			b.WriteString("无\n")
		}
		for _, k := range missing {
			fmt.Fprintf(&b, "- `%s` %s\n", k, concepts[k].Name)
		}
	}
	return writeFileAtomic(path, []byte(b.String()))
}

func writeMapping(path string, p *plan) error {
	var b strings.Builder
	b.WriteString("临时编号 → 正式题号\n\n")
	refs := make([]string, 0, len(p.refToID))
	for r := range p.refToID {
		refs = append(refs, r)
	}
	sort.Slice(refs, func(i, j int) bool {
		return idLess(p.refToID[refs[i]], p.refToID[refs[j]])
	})
	for _, r := range refs {
		fmt.Fprintf(&b, "%-5s → %-9s %s\n", r, p.refToID[r], p.refTitle[r])
	}
	return os.WriteFile(path, []byte(b.String()), 0644)
}

func mdCell(s string) string {
	s = strings.ReplaceAll(s, "|", "｜")
	s = strings.ReplaceAll(s, "\n", " ")
	return s
}

func title(s string) {
	fmt.Println(strings.Repeat("═", 60))
	fmt.Println("  " + s)
	fmt.Println(strings.Repeat("═", 60))
}

func section(s string) {
	fmt.Printf("\n── %s %s\n", s, strings.Repeat("─", max(2, 50-len([]rune(s)))))
}

func fail(format string, a ...any) {
	fmt.Printf("\n  ❌ "+format+"\n", a...)
}
