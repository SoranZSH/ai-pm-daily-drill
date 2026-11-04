package main

// 题库编写规范 v2.1 新增字段的校验（解析页「对答案层」与「讲透层」）。
// 这些字段都是可选的：旧题没有它们照常导入；只要出现任意一个，就按 v2.1 的要求检查。
// 会让解析页显示错乱的问题（类型不对、内容为空、a_en 与 a_pairs 拼不上）算错误，其余算提醒。

import (
	"encoding/json"
	"fmt"
	"regexp"
	"strings"
	"unicode"
)

// 正文里引用临时编号（N12）或题号：导入后临时编号会换成正式题号，但正文不会跟着改
var refInTextRe = regexp.MustCompile(`(^|[^A-Za-z0-9-])N\d{1,3}([^0-9]|$)`)

var v21Fields = []string{"gist", "points", "a_pairs", "basics", "pitfalls", "walkthrough", "method"}

var phraseTypes = map[string]bool{"词汇": true, "搭配": true, "句型": true}

type v21Phrase struct {
	En    string `json:"en"`
	Cn    string `json:"cn"`
	Type  string `json:"type"`
	Usage string `json:"usage"`
}

type v21Item struct {
	Gist   *bilingual  `json:"gist"`
	Points []bilingual `json:"points"`
	APairs []bilingual `json:"a_pairs"`
	Basics []struct {
		Term    string `json:"term"`
		TermEn  string `json:"term_en"`
		Explain string `json:"explain"`
		Analogy string `json:"analogy"`
	} `json:"basics"`
	Pitfalls []struct {
		Wrong string `json:"wrong"`
		Why   string `json:"why"`
		Right string `json:"right"`
	} `json:"pitfalls"`
	Walkthrough []string `json:"walkthrough"`
	Method      *struct {
		Name     string   `json:"name"`
		Steps    []string `json:"steps"`
		Transfer string   `json:"transfer"`
	} `json:"method"`
	KeyPhrases []v21Phrase `json:"key_phrases"`
}

func normEn(s string) string { return strings.Join(strings.Fields(s), " ") }

func normCn(s string) string {
	return strings.Map(func(r rune) rune {
		if unicode.IsSpace(r) {
			return -1
		}
		return r
	}, s)
}

func blank(s string) bool { return strings.TrimSpace(s) == "" }

// validateV21 返回（提醒, 错误）。obj 用来判断字段是否出现。
func validateV21(obj object, raw json.RawMessage, it itemInfo) ([]string, []string) {
	var warns, errs []string
	present := map[string]bool{}
	any := false
	for _, k := range v21Fields {
		if obj.has(k) {
			present[k] = true
			any = true
		}
	}
	if !any {
		return nil, nil // 旧格式题目：不做 v2.1 检查
	}
	var v v21Item
	if err := json.Unmarshal(raw, &v); err != nil {
		return nil, []string{"v2.1 字段类型不对（对照规范第六节的格式）：" + err.Error()}
	}
	deep := it.Level == "X" || it.Difficulty == "较难"
	aEn := normEn(it.AEn)

	// 对答案层
	if !present["gist"] {
		warns = append(warns, "缺少 gist（一句话答案），解析页第一层会少掉结论")
	} else if v.Gist == nil || blank(v.Gist.Cn) || blank(v.Gist.En) {
		errs = append(errs, "gist 的 cn / en 都要写")
	} else {
		if n := len([]rune(strings.TrimSpace(v.Gist.Cn))); n > 40 {
			warns = append(warns, fmt.Sprintf("gist.cn 有 %d 字，建议不超过 40 字", n))
		}
		if n := len(strings.Fields(v.Gist.En)); n > 20 {
			warns = append(warns, fmt.Sprintf("gist.en 有 %d 词，建议不超过 20 词", n))
		}
	}

	if !present["points"] {
		warns = append(warns, "缺少 points（采分要点），解析页不能做要点自查")
	} else {
		if n := len(v.Points); n < 3 || n > 5 {
			warns = append(warns, fmt.Sprintf("points 有 %d 条，建议 3–5 条", n))
		}
		for i, p := range v.Points {
			if blank(p.Cn) || blank(p.En) {
				errs = append(errs, fmt.Sprintf("points 第 %d 条的 cn / en 不能为空", i+1))
				continue
			}
			if !strings.Contains(aEn, normEn(p.En)) {
				warns = append(warns, fmt.Sprintf("points 第 %d 条的 en「%s」在 a_en 里找不到原文", i+1, p.En))
			}
			if n := len([]rune(strings.TrimSpace(p.Cn))); n > 30 {
				warns = append(warns, fmt.Sprintf("points 第 %d 条 cn 有 %d 字，建议不超过 30 字", i+1, n))
			}
		}
	}

	if !present["a_pairs"] {
		warns = append(warns, "缺少 a_pairs（逐句对照），解析页会改为整段显示中英文")
	} else {
		ok := true
		for i, p := range v.APairs {
			if blank(p.En) || blank(p.Cn) {
				errs = append(errs, fmt.Sprintf("a_pairs 第 %d 项的 en / cn 不能为空", i+1))
				ok = false
			}
		}
		if n := len(v.APairs); n < 5 || n > 9 {
			warns = append(warns, fmt.Sprintf("a_pairs 有 %d 句，建议 5–9 句", n))
		}
		if ok && len(v.APairs) > 0 {
			ens, cns := make([]string, len(v.APairs)), make([]string, len(v.APairs))
			for i, p := range v.APairs {
				ens[i], cns[i] = p.En, p.Cn
			}
			if normEn(strings.Join(ens, " ")) != aEn {
				errs = append(errs, "a_en 与 a_pairs 各句 en 用空格连接的结果不一致（规范 6.3：a_en 必须由 a_pairs 拼出）")
			}
			if normCn(strings.Join(cns, "")) != normCn(it.ACn) {
				errs = append(errs, "a_cn 与 a_pairs 各句 cn 连接的结果不一致（规范 6.3：a_cn 必须由 a_pairs 拼出）")
			}
		}
	}

	// 表达积累
	types := map[string]bool{}
	for i, kp := range v.KeyPhrases {
		if blank(kp.En) {
			continue // 空值已由基础校验报错
		}
		if !strings.Contains(aEn, normEn(kp.En)) {
			warns = append(warns, fmt.Sprintf("key_phrases 第 %d 条「%s」在 a_en 里找不到原文，解析页无法划线", i+1, kp.En))
		}
		switch {
		case blank(kp.Type):
			warns = append(warns, fmt.Sprintf("key_phrases 第 %d 条缺少 type（词汇 / 搭配 / 句型）", i+1))
		case !phraseTypes[strings.TrimSpace(kp.Type)]:
			warns = append(warns, fmt.Sprintf("key_phrases 第 %d 条的 type「%s」不是 词汇 / 搭配 / 句型", i+1, kp.Type))
		default:
			types[strings.TrimSpace(kp.Type)] = true
		}
		if blank(kp.Usage) {
			warns = append(warns, fmt.Sprintf("key_phrases 第 %d 条缺少 usage（怎么用）", i+1))
		}
	}
	if len(v.KeyPhrases) >= 4 && len(types) == 1 {
		warns = append(warns, "key_phrases 只用了一种 type，建议至少两种")
	}

	// 讲透层
	if present["basics"] {
		if len(v.Basics) > 3 {
			warns = append(warns, fmt.Sprintf("basics 有 %d 条，建议不超过 3 条", len(v.Basics)))
		}
		for i, b := range v.Basics {
			if blank(b.Term) || blank(b.Explain) {
				errs = append(errs, fmt.Sprintf("basics 第 %d 条的 term / explain 不能为空", i+1))
			}
		}
	} else if deep {
		warns = append(warns, "拓展题或较难题应写 basics（先补基础概念）")
	}

	if !present["pitfalls"] {
		warns = append(warns, "缺少 pitfalls（常见误区）")
	} else {
		if len(v.Pitfalls) == 0 || len(v.Pitfalls) > 2 {
			warns = append(warns, fmt.Sprintf("pitfalls 有 %d 条，建议 1–2 条", len(v.Pitfalls)))
		}
		for i, p := range v.Pitfalls {
			if blank(p.Wrong) || blank(p.Why) || blank(p.Right) {
				errs = append(errs, fmt.Sprintf("pitfalls 第 %d 条的 wrong / why / right 都要写", i+1))
			}
		}
	}

	if present["walkthrough"] {
		if n := len(v.Walkthrough); n < 3 || n > 5 {
			warns = append(warns, fmt.Sprintf("walkthrough 有 %d 步，建议 3–5 步", n))
		}
		for i, s := range v.Walkthrough {
			if blank(s) {
				errs = append(errs, fmt.Sprintf("walkthrough 第 %d 步是空的", i+1))
			}
		}
	} else if deep {
		warns = append(warns, "拓展题或较难题应写 walkthrough（难点拆解）")
	}

	if present["method"] {
		if v.Method == nil || blank(v.Method.Name) || len(v.Method.Steps) == 0 || blank(v.Method.Transfer) {
			errs = append(errs, "method 的 name / steps / transfer 都要写")
		} else {
			for i, s := range v.Method.Steps {
				if blank(s) {
					errs = append(errs, fmt.Sprintf("method.steps 第 %d 步是空的", i+1))
				}
			}
		}
	} else if deep || it.Kind != "knowledge" {
		warns = append(warns, "缺少 method（思维方法）；只有基础题且 kind=knowledge 时可以不写")
	}
	if hits := refsInText(raw); len(hits) > 0 {
		warns = append(warns, fmt.Sprintf("正文里出现了临时编号（%s）。导入后编号会变，正文不会跟着改，请改成知识点名称", strings.Join(hits, "、")))
	}
	return warns, errs
}

// refsInText 检查展示给学习者的文字字段里有没有临时编号
func refsInText(raw json.RawMessage) []string {
	var m map[string]json.RawMessage
	if json.Unmarshal(raw, &m) != nil {
		return nil
	}
	var hits []string
	for _, k := range []string{"concept", "approach", "tips", "walkthrough", "method", "basics", "pitfalls", "gist", "points", "a_pairs", "a_en", "a_cn"} {
		if v, ok := m[k]; ok && refInTextRe.Match(v) {
			hits = append(hits, k)
		}
	}
	return hits
}
