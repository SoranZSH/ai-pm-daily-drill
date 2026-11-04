package main

// 规范 v2.1 新增字段的校验用例。

import (
	"encoding/json"
	"strings"
	"testing"
)

const sent = "The core idea is simple and practical for product teams."

// v21 返回一组合法的 v2.1 字段：a_pairs 能拼出 item() 默认的 a_en / a_cn
func v21(level string) map[string]any {
	pairs := make([]map[string]string, 16)
	for i := range pairs {
		pairs[i] = map[string]string{"en": sent, "cn": "这是逐句对照的中文翻译内容。"}
	}
	m := map[string]any{
		"a_cn":    strings.Repeat("这是逐句对照的中文翻译内容。", 16),
		"gist":    map[string]string{"cn": "核心想法简单实用。", "en": "The core idea is simple."},
		"points":  []map[string]string{{"cn": "核心想法", "en": "core idea"}, {"cn": "简单", "en": "simple"}, {"cn": "面向产品团队", "en": "product teams"}},
		"a_pairs": pairs,
		"key_phrases": []map[string]string{
			{"en": "core idea", "cn": "核心", "type": "词汇", "usage": "引出结论时用"},
			{"en": "simple and practical", "cn": "简单实用", "type": "搭配", "usage": "形容方案落地性"},
			{"en": "practical", "cn": "实用", "type": "词汇", "usage": "比 useful 更强调能落地"},
			{"en": "product teams", "cn": "产品团队", "type": "词汇", "usage": "泛指做产品的人"}},
		"pitfalls": []map[string]string{{"wrong": "以为很复杂。", "why": "其实机制很直接。", "right": "先看它解决什么问题。"}},
	}
	if level == "X" {
		m["kind"] = "idea"
		m["basics"] = []map[string]string{{"term": "工具调用", "term_en": "tool calling", "explain": "让模型调用外部函数。", "analogy": "像打电话求助。"}}
		m["walkthrough"] = []string{"拆题：问的是取舍。", "定位：找问题根源。", "给顺序：先简单后复杂。"}
		m["method"] = map[string]any{"name": "诊断式取舍", "steps": []string{"找根源", "列约束", "给顺序"}, "transfer": "适用于各种选型题。"}
	}
	return m
}

func TestV21ImportKeepsFields(t *testing.T) {
	e := newEnv(t)
	seed(e)
	e.writeUpdate("题库更新_20261030.json", "incremental", map[string]any{"file": "04_agents.json", "items": []map[string]any{
		item("ref", "N1", "F", []string{}, v21("F")),
		item("ref", "N2", "X", []string{"N1"}, v21("X")),
	}})
	if code := e.run("", ""); code != 0 {
		t.Fatalf("合法的 v2.1 题目应能导入，code=%d", code)
	}
	cats, _ := loadBank(e.bank)
	found := 0
	for _, c := range cats {
		for _, r := range c.Items {
			var m map[string]json.RawMessage
			json.Unmarshal(r, &m)
			if _, ok := m["a_pairs"]; ok {
				found++
				if _, ok := m["gist"]; !ok {
					t.Fatalf("gist 没有保留")
				}
			}
		}
	}
	if found != 2 {
		t.Fatalf("应保留 2 道 v2.1 题，实际 %d", found)
	}
}

func TestV21Errors(t *testing.T) {
	e := newEnv(t)
	seed(e)
	agents := func(extra map[string]any) map[string]any {
		x := v21("F")
		for k, v := range extra {
			x[k] = v
		}
		return map[string]any{"file": "04_agents.json", "items": []map[string]any{item("ref", "N1", "F", []string{}, x)}}
	}
	// a_en 与 a_pairs 拼不上
	e.writeUpdate("题库更新_20261031.json", "incremental", agents(map[string]any{"a_en": answer() + " Extra sentence."}))
	e.mustFail("题库更新_20261031.json")
	// a_cn 与 a_pairs 拼不上
	e.writeUpdate("题库更新_20261031.json", "incremental", agents(map[string]any{"a_cn": "完全不同的中文。"}))
	e.mustFail("题库更新_20261031.json")
	// gist 缺 cn
	e.writeUpdate("题库更新_20261031.json", "incremental", agents(map[string]any{"gist": map[string]string{"en": "x"}}))
	e.mustFail("题库更新_20261031.json")
	// 类型不对
	e.writeUpdate("题库更新_20261031.json", "incremental", agents(map[string]any{"points": "不是列表"}))
	e.mustFail("题库更新_20261031.json")
	// pitfalls 不完整
	e.writeUpdate("题库更新_20261031.json", "incremental", agents(map[string]any{"pitfalls": []map[string]string{{"wrong": "x"}}}))
	e.mustFail("题库更新_20261031.json")
}

func TestV21Warnings(t *testing.T) {
	check := func(level string, extra map[string]any, drop []string) []string {
		m := item("ref", "N1", level, []string{}, v21(level))
		for k, v := range extra {
			m[k] = v
		}
		for _, k := range drop {
			delete(m, k)
		}
		raw, _ := json.Marshal(m)
		obj, _ := parseObject(raw)
		w, e := validateV21(obj, raw, infoOf(raw))
		if len(e) > 0 {
			t.Fatalf("不应有错误：%v", e)
		}
		var out []string // 测试用答案有 16 句，忽略句数提醒
		for _, x := range w {
			if !strings.Contains(x, "a_pairs 有") {
				out = append(out, x)
			}
		}
		return out
	}
	has := func(ws []string, sub string) bool {
		for _, w := range ws {
			if strings.Contains(w, sub) {
				return true
			}
		}
		return false
	}
	if w := check("F", nil, nil); len(w) != 0 {
		t.Fatalf("合法基础题不应有提醒：%v", w)
	}
	if w := check("X", nil, nil); len(w) != 0 {
		t.Fatalf("合法拓展题不应有提醒：%v", w)
	}
	if !has(check("X", nil, []string{"walkthrough"}), "walkthrough") {
		t.Fatalf("拓展题缺 walkthrough 应提醒")
	}
	if !has(check("F", map[string]any{"points": []map[string]string{{"cn": "a", "en": "not in answer"}, {"cn": "b", "en": "simple"}, {"cn": "c", "en": "core idea"}}}, nil), "找不到原文") {
		t.Fatalf("points.en 不在 a_en 中应提醒")
	}
	if !has(check("F", map[string]any{"kind": "method"}, nil), "method") {
		t.Fatalf("method 题缺 method 字段应提醒")
	}
	if !has(check("F", map[string]any{"tips": "可延伸至 KV 缓存（N52）。"}, nil), "临时编号") {
		t.Fatalf("正文里的临时编号应提醒")
	}
	if has(check("F", map[string]any{"tips": "参考 AGT-N12 与 GPT-4o。"}, nil), "临时编号") {
		t.Fatalf("不应把 AGT-N12、GPT-4o 误判为临时编号")
	}
	// 旧格式题目不做 v2.1 检查
	raw, _ := json.Marshal(item("ref", "N1", "F", []string{}, nil))
	obj, _ := parseObject(raw)
	if w, e := validateV21(obj, raw, infoOf(raw)); len(w)+len(e) != 0 {
		t.Fatalf("旧格式题目不应触发 v2.1 检查")
	}
}
