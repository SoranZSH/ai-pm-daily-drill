package main

// M1 验收用例。运行：go test ./...

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

type env struct {
	t        *testing.T
	gh, bank string
}

func newEnv(t *testing.T) *env {
	gh := filepath.Join(t.TempDir(), "Github学习")
	bank := filepath.Join(gh, "当前题库")
	os.MkdirAll(bank, 0755)
	cm := `{"version":1,"concepts":{"agt.tool_calling":{"name":"工具调用","domain":"AGT","aliases":[]},
	 "agt.planning":{"name":"任务规划","domain":"AGT","aliases":[]},"rag.embedding":{"name":"Embedding","domain":"RAG","aliases":[]}}}`
	os.WriteFile(filepath.Join(gh, conceptsName), []byte(cm), 0644)
	return &env{t, gh, bank}
}

func answer() string {
	return strings.TrimSpace(strings.Repeat("The core idea is simple and practical for product teams. ", 16))
}

// item 生成一道内容合法的题；key 为 "ref" 或 "id"
func item(key, code, level string, prereq []string, extra map[string]any) map[string]any {
	m := map[string]any{
		key: code, "level": level, "kind": "knowledge", "difficulty": "中等",
		"tags": []string{"测试"}, "concepts": []string{"agt.tool_calling"}, "prereq": prereq,
		"q_cn": "测试题目 " + code + "：工具调用是什么？", "q_en": "What is tool calling?",
		"concept": map[string]string{"cn": "概念解析中文。", "en": "Concept in English."},
		"a_en":    answer(), "a_cn": strings.Repeat("这是逐句对照的中文翻译内容。", 15),
		"key_phrases": []map[string]string{{"en": "core idea", "cn": "核心"}, {"en": "simple", "cn": "简单"},
			{"en": "practical", "cn": "实用"}, {"en": "product teams", "cn": "产品团队"}},
		"approach": "先定义再举例。", "tips": "记住核心一句。",
	}
	for k, v := range extra {
		m[k] = v
	}
	return m
}

func cat(file, name, domain string, items []map[string]any, extra map[string]any) map[string]any {
	m := map[string]any{"file": file, "category": name, "category_en": name + " EN", "domain": domain, "items": items}
	for k, v := range extra {
		m[k] = v
	}
	return m
}

func (e *env) writeUpdate(name, bankMode string, cats ...map[string]any) {
	doc := map[string]any{"format": formatV2, "bank_mode": bankMode, "categories": cats}
	b, _ := json.MarshalIndent(doc, "", "  ")
	if err := os.WriteFile(filepath.Join(e.gh, name), b, 0644); err != nil {
		e.t.Fatal(err)
	}
}

func (e *env) run(mode, file string) int {
	return run(options{dir: e.gh, bank: e.bank, mode: mode, file: file, yes: true, today: "2026-10-12"})
}

func (e *env) runOn(mode, file, today string) int {
	return run(options{dir: e.gh, bank: e.bank, mode: mode, file: file, yes: true, today: today})
}

func (e *env) items() map[string]itemInfo {
	cats, err := loadBank(e.bank)
	if err != nil {
		e.t.Fatal(err)
	}
	out := map[string]itemInfo{}
	for _, c := range cats {
		for _, r := range c.Items {
			it := infoOf(r)
			out[it.ID] = it
		}
	}
	return out
}

func (e *env) files() []string {
	es, _ := os.ReadDir(e.bank)
	var out []string
	for _, x := range es {
		out = append(out, x.Name())
	}
	return out
}

func (e *env) bankSnapshot() string {
	var b strings.Builder
	for _, f := range e.files() {
		d, _ := os.ReadFile(filepath.Join(e.bank, f))
		b.WriteString(f + "\n" + string(d))
	}
	return b.String()
}

func (e *env) mustFail(name string) {
	e.t.Helper()
	before := e.bankSnapshot()
	if code := e.run("", name); code == 0 {
		e.t.Fatalf("%s 应当失败，但返回 0", name)
	}
	if e.bankSnapshot() != before {
		e.t.Fatalf("%s 失败后题库被改动了", name)
	}
	os.Remove(filepath.Join(e.gh, name))
}

// 用例 1：空题库 + 覆盖导入
func seed(e *env) {
	e.writeUpdate("题库更新_20261012.json", "overwrite",
		cat("04_agents.json", "智能体", "AGT", []map[string]any{
			item("ref", "N1", "F", []string{}, nil),
			item("ref", "N2", "F", []string{"N1"}, nil),
			item("ref", "N3", "X", []string{"N1", "N2"}, map[string]any{"kind": "idea"}),
		}, nil),
		cat("03_rag.json", "检索增强", "RAG", []map[string]any{
			item("ref", "N4", "F", []string{}, map[string]any{"concepts": []string{"rag.embedding"}}),
			item("ref", "N5", "F", []string{}, map[string]any{"concepts": []string{"rag.embedding"}}),
			item("ref", "N6", "X", []string{"N4"}, nil),
		}, nil))
	if code := e.run("overwrite", ""); code != 0 {
		e.t.Fatalf("用例1 导入失败 code=%d", code)
	}
}

func TestCase01OverwriteIntoEmpty(t *testing.T) {
	e := newEnv(t)
	seed(e)
	it := e.items()
	for _, id := range []string{"AGT-F001", "AGT-F002", "AGT-X001", "RAG-F001", "RAG-F002", "RAG-X001"} {
		if _, ok := it[id]; !ok {
			t.Fatalf("缺少题号 %s；现有 %v", id, it)
		}
	}
	if got := strings.Join(it["AGT-X001"].Prereq, ","); got != "AGT-F001,AGT-F002" {
		t.Fatalf("prereq 未替换：%s", got)
	}
	if it["AGT-F001"].Added != "2026-10-12" {
		t.Fatalf("added 未写入")
	}
	if it["AGT-F001"].Ref != "" {
		t.Fatalf("ref 字段应被去掉")
	}
	reg, _ := loadRegistry(filepath.Join(e.gh, registryName), e.bank)
	if reg.Max["AGT-F"] != 2 || reg.Max["AGT-X"] != 1 {
		t.Fatalf("题号登记不对：%v", reg.Max)
	}
	if _, err := os.Stat(filepath.Join(e.gh, catalogName)); err != nil {
		t.Fatalf("没生成题库目录")
	}
	if _, err := os.Stat(filepath.Join(e.gh, archiveDir, "题库更新_20261012.json.题号对照.txt")); err != nil {
		t.Fatalf("没生成题号对照表")
	}
}

// 用例 2：增量 新增 / 修改 / 删除
func TestCase02Incremental(t *testing.T) {
	e := newEnv(t)
	seed(e)
	edit := item("id", "AGT-F002", "F", []string{"AGT-F001"}, map[string]any{"q_cn": "改过的题目：如何选择工具？"})
	e.writeUpdate("题库更新_20261013.json", "incremental",
		map[string]any{"file": "04_agents.json", "items": []map[string]any{
			item("ref", "N1", "F", []string{}, nil), edit}, "delete_ids": []string{"AGT-X001"}})
	if code := e.runOn("", "", "2026-10-13"); code != 0 {
		t.Fatalf("导入失败 %d", code)
	}
	it := e.items()
	if _, ok := it["AGT-F003"]; !ok {
		t.Fatalf("新题号应接续为 AGT-F003")
	}
	if it["AGT-F002"].QCn != "改过的题目：如何选择工具？" || it["AGT-F002"].Added != "2026-10-12" {
		t.Fatalf("改题内容或 added 不对：%+v", it["AGT-F002"])
	}
	if it["AGT-F003"].Added != "2026-10-13" {
		t.Fatalf("新题 added 应为当天")
	}
	if _, ok := it["AGT-X001"]; ok {
		t.Fatalf("AGT-X001 应被删除")
	}
}

// 用例 3：再次覆盖，序号不复用
func TestCase03OverwriteNoReuse(t *testing.T) {
	e := newEnv(t)
	seed(e)
	e.writeUpdate("题库更新_20261014.json", "overwrite",
		cat("04_agents.json", "智能体", "AGT", []map[string]any{item("ref", "N1", "F", []string{}, nil)}, nil))
	if code := e.run("overwrite", ""); code != 0 {
		t.Fatalf("覆盖失败")
	}
	if f := e.files(); len(f) != 1 || f[0] != "04_agents.json" {
		t.Fatalf("旧分类应全部消失：%v", f)
	}
	it := e.items()
	if _, ok := it["AGT-F003"]; !ok || len(it) != 1 {
		t.Fatalf("新题号应为 AGT-F003：%v", it)
	}
	bk, _ := os.ReadDir(filepath.Join(e.gh, backupName))
	if len(bk) == 0 {
		t.Fatalf("应有备份")
	}
}

// 用例 4：删除题号登记后重建，仍不重复
func TestCase04RegistryRebuild(t *testing.T) {
	e := newEnv(t)
	seed(e)
	e.writeUpdate("题库更新_20261014.json", "overwrite",
		cat("04_agents.json", "智能体", "AGT", []map[string]any{item("ref", "N1", "F", []string{}, nil)}, nil))
	e.run("overwrite", "") // 现在题库只有 AGT-F003；AGT-F001/F002 只存在于备份
	os.Remove(filepath.Join(e.gh, registryName))
	e.writeUpdate("题库更新_20261015.json", "incremental",
		map[string]any{"file": "04_agents.json", "items": []map[string]any{item("ref", "N1", "F", []string{}, nil)}})
	if code := e.run("incremental", ""); code != 0 {
		t.Fatalf("导入失败")
	}
	if _, ok := e.items()["AGT-F004"]; !ok {
		t.Fatalf("重建后应分配 AGT-F004：%v", e.items())
	}
}

func TestCase05to13Errors(t *testing.T) {
	e := newEnv(t)
	seed(e)
	agents := func(items ...map[string]any) map[string]any {
		return map[string]any{"file": "04_agents.json", "items": items}
	}
	// 5 X 前置为空
	e.writeUpdate("题库更新_20261020.json", "incremental", agents(item("ref", "N1", "X", []string{}, nil)))
	e.mustFail("题库更新_20261020.json")
	// 6 X 前置只有 X
	e.writeUpdate("题库更新_20261020.json", "incremental", agents(item("ref", "N1", "X", []string{"AGT-X001"}, nil)))
	e.mustFail("题库更新_20261020.json")
	// 7 前置不存在
	e.writeUpdate("题库更新_20261020.json", "incremental", agents(item("ref", "N1", "X", []string{"N9"}, nil)))
	e.mustFail("题库更新_20261020.json")
	e.writeUpdate("题库更新_20261020.json", "incremental", agents(item("ref", "N1", "X", []string{"AGT-F099"}, nil)))
	e.mustFail("题库更新_20261020.json")
	// 8 循环
	e.writeUpdate("题库更新_20261020.json", "incremental", agents(
		item("ref", "N1", "F", []string{"N2"}, nil), item("ref", "N2", "F", []string{"N1"}, nil)))
	e.mustFail("题库更新_20261020.json")
	// 9 前置在 delete_ids 中
	c := agents(item("ref", "N1", "X", []string{"AGT-F002"}, nil))
	c["delete_ids"] = []string{"AGT-F002"}
	e.writeUpdate("题库更新_20261020.json", "incremental", c)
	e.mustFail("题库更新_20261020.json")
	// 10 覆盖模式含 id / delete_ids
	e.writeUpdate("题库更新_20261020.json", "overwrite",
		cat("04_agents.json", "智能体", "AGT", []map[string]any{item("id", "AGT-F001", "F", []string{}, nil)}, nil))
	if code := e.run("overwrite", "题库更新_20261020.json"); code == 0 {
		t.Fatalf("用例10 应失败")
	}
	os.Remove(filepath.Join(e.gh, "题库更新_20261020.json"))
	e.writeUpdate("题库更新_20261020.json", "overwrite",
		cat("04_agents.json", "智能体", "AGT", []map[string]any{item("ref", "N1", "F", []string{}, nil)},
			map[string]any{"delete_ids": []string{"AGT-F001"}}))
	if code := e.run("overwrite", "题库更新_20261020.json"); code == 0 {
		t.Fatalf("用例10b 应失败")
	}
	os.Remove(filepath.Join(e.gh, "题库更新_20261020.json"))
	// 11 v1 格式
	os.WriteFile(filepath.Join(e.gh, "题库更新_20261020.json"), []byte(`{"categories":[{"file":"04_agents.json","items":[]}]}`), 0644)
	e.mustFail("题库更新_20261020.json")
	// 12 ref 重复 / 格式错 / 与 id 同时出现
	e.writeUpdate("题库更新_20261020.json", "incremental", agents(item("ref", "N1", "F", []string{}, nil), item("ref", "N1", "F", []string{}, nil)))
	e.mustFail("题库更新_20261020.json")
	e.writeUpdate("题库更新_20261020.json", "incremental", agents(item("ref", "A1", "F", []string{}, nil)))
	e.mustFail("题库更新_20261020.json")
	e.writeUpdate("题库更新_20261020.json", "incremental", agents(item("ref", "N1", "F", []string{}, map[string]any{"id": "AGT-F001"})))
	e.mustFail("题库更新_20261020.json")
	// 13 改题时 level 与题号不一致
	e.writeUpdate("题库更新_20261020.json", "incremental", agents(item("id", "AGT-F001", "X", []string{"AGT-F002"}, nil)))
	e.mustFail("题库更新_20261020.json")
}

// 用例 14：未知概念只提醒
func TestCase14UnknownConcept(t *testing.T) {
	e := newEnv(t)
	seed(e)
	e.writeUpdate("题库更新_20261021.json", "incremental", map[string]any{"file": "04_agents.json",
		"items": []map[string]any{item("ref", "N1", "F", []string{}, map[string]any{"concepts": []string{"agt.brand_new"}})}})
	if code := e.run("", ""); code != 0 {
		t.Fatalf("未知概念不应阻止导入")
	}
}

// 用例 15：多份文件，--file 指定
func TestCase15ChooseFile(t *testing.T) {
	e := newEnv(t)
	seed(e)
	for _, n := range []string{"题库更新_20261021.json", "题库更新_20261022.json", "题库更新_20261022_2.json"} {
		e.writeUpdate(n, "incremental", map[string]any{"file": "04_agents.json",
			"items": []map[string]any{item("ref", "N1", "F", []string{}, map[string]any{"q_cn": "来自 " + n})}})
	}
	fs, _ := findUpdates(e.gh)
	if len(fs) != 3 || filepath.Base(fs[2]) != "题库更新_20261022_2.json" {
		t.Fatalf("排序不对：%v", fs)
	}
	if code := e.run("", "题库更新_20261021.json"); code != 0 {
		t.Fatalf("--file 导入失败")
	}
	found := false
	for _, it := range e.items() {
		if it.QCn == "来自 题库更新_20261021.json" {
			found = true
		}
	}
	if !found {
		t.Fatalf("没有导入指定文件")
	}
}

// 用例 16：模板原样导入应失败
func TestCase16Template(t *testing.T) {
	e := newEnv(t)
	tpl, err := os.ReadFile(filepath.Join("..", "..", "题库模板", "题库更新_模板.json"))
	if err != nil {
		t.Skip("找不到模板文件（在 工具源码\\题库更新 目录下运行 go test 时会读取）")
	}
	os.WriteFile(filepath.Join(e.gh, "题库更新_20261023.json"), tpl, 0644)
	e.mustFail("题库更新_20261023.json")
}

// 现有题的前置被删除时要拦下
func TestDeletePrereqOfExisting(t *testing.T) {
	e := newEnv(t)
	seed(e)
	e.writeUpdate("题库更新_20261024.json", "incremental", map[string]any{"file": "04_agents.json",
		"items": []map[string]any{}, "delete_ids": []string{"AGT-F001"}})
	e.mustFail("题库更新_20261024.json")
}

// 换行风格与旧分类保持一致；目录列出未覆盖概念
func TestCatalogAndCRLF(t *testing.T) {
	e := newEnv(t)
	seed(e)
	d, _ := os.ReadFile(filepath.Join(e.bank, "04_agents.json"))
	if !strings.Contains(string(d), "\r\n") {
		t.Fatalf("新分类文件应使用 Windows 换行")
	}
	cat, _ := os.ReadFile(filepath.Join(e.gh, catalogName))
	if !strings.Contains(string(cat), "agt.planning") || !strings.Contains(string(cat), "| AGT-X001 | X |") {
		t.Fatalf("题库目录内容不对：\n%s", cat)
	}
}
