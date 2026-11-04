// 题库更新.exe —— 「每日一题」题库导入工具（契约① v2 → 契约② v2）
//
// 双击运行：列出本程序所在文件夹根目录下的「题库更新_*.json」→ 校验 → 选择【增量添加】或【题库覆盖】
// → 分配正式题号 → 预览 → 确认 → 备份 → 写入「当前题库」→ 生成「题库目录.md」→ 归档到「已导入」。
//
// 命令行参数（测试用）：
//
//	--dir  <文件夹>   扫描哪个文件夹（默认：exe 所在文件夹）
//	--bank <文件夹>   题库目录（默认：exe 旁边的「当前题库」）
//	--file <文件名>   指定要导入的更新文件（默认：最新一份）
//	--mode incremental|overwrite   不询问，直接使用该模式
//	--yes             不询问确认
//	--no-pause        结束时不等回车
package main

import (
	"bufio"
	"bytes"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strconv"
	"strings"
	"time"
)

const (
	defaultBank  = "当前题库" // 相对 exe 所在文件夹
	backupName   = "题库备份"
	configName   = "题库更新配置.json"
	archiveDir   = "已导入"
	registryName = "题号登记.json"
	catalogName  = "题库目录.md"
	conceptsName = "知识地图.json"
	keepBackups  = 20
)

var updateNameRe = regexp.MustCompile(`^题库更新_(\d{8})(?:_(\d+))?\.json$`)

type options struct {
	dir, bank, file, mode string
	yes                   bool
	in                    *bufio.Reader
	today                 string
}

type config struct {
	BankDir string `json:"bank_dir"`
	ScanDir string `json:"scan_dir"`
}

func main() {
	setupConsole()
	var o options
	flag.StringVar(&o.dir, "dir", "", "扫描文件夹")
	flag.StringVar(&o.bank, "bank", "", "题库目录")
	flag.StringVar(&o.file, "file", "", "要导入的更新文件名")
	flag.StringVar(&o.mode, "mode", "", "incremental 或 overwrite")
	flag.BoolVar(&o.yes, "yes", false, "不询问确认")
	noPause := flag.Bool("no-pause", false, "结束时不等回车")
	flag.Parse()
	o.in = bufio.NewReader(os.Stdin)
	o.today = time.Now().Format("2006-01-02")

	code := run(o)
	if !*noPause {
		fmt.Print("\n按回车键关闭窗口…")
		o.in.ReadString('\n')
	}
	os.Exit(code)
}

func run(o options) int {
	exeDir := exeFolder()
	cfg := loadConfig(exeDir)
	scanDir := absFrom(exeDir, firstNonEmpty(o.dir, cfg.ScanDir, exeDir))
	bankDir := absFrom(exeDir, firstNonEmpty(o.bank, cfg.BankDir, defaultBank))
	home := filepath.Dir(bankDir) // Github学习
	registryPath := filepath.Join(home, registryName)
	catalogPath := filepath.Join(home, catalogName)
	concepts := loadConceptMap(filepath.Join(home, conceptsName))
	if o.today == "" {
		o.today = time.Now().Format("2006-01-02")
	}

	title("每日一题 · 题库更新工具 v2")
	fmt.Printf("  扫描目录：%s\n  题库目录：%s\n", scanDir, bankDir)
	if concepts == nil {
		fmt.Printf("  ⚠ 没找到 %s，跳过概念键检查\n", conceptsName)
	}

	if st, err := os.Stat(bankDir); err != nil || !st.IsDir() {
		fail("找不到题库目录 %s\n  如果项目搬了位置，在 exe 旁边建一个「%s」，写上：\n  {\"bank_dir\": \"题库文件夹路径（可写相对 exe 的路径）\"}", bankDir, configName)
		return 1
	}
	bank, err := loadBank(bankDir)
	if err != nil {
		fail("读取现有题库失败：%v", err)
		return 1
	}

	files, err := findUpdates(scanDir)
	if err != nil {
		fail("扫描目录失败：%v", err)
		return 1
	}
	if len(files) == 0 {
		fmt.Printf("\n  没找到更新文件。请把文件命名为「题库更新_%s.json」放在扫描目录根下（同一天多份加 _2、_3）。\n", strings.ReplaceAll(o.today, "-", ""))
		printOverview(bank)
		if err := writeCatalog(catalogPath, bank, concepts); err == nil {
			fmt.Printf("  已刷新 %s\n", catalogName)
		}
		return 0
	}

	target, ok := chooseFile(files, o)
	if !ok {
		return 1
	}
	fmt.Printf("\n  本次导入：%s\n", filepath.Base(target))

	pu, warns, errs := parseUpdate(target, concepts)
	if len(errs) > 0 {
		reportErrors(errs, warns)
		return 2
	}

	mode, ok := chooseMode(pu.file.BankMode, o)
	if !ok {
		return 1
	}

	reg, rebuilt := loadRegistry(registryPath, bankDir)
	if rebuilt {
		fmt.Printf("  ⚠ 没找到 %s，已根据当前题库和全部备份重建\n", registryName)
	}
	p, w2, e2 := buildPlan(pu, bank, mode, reg, o.today)
	warns = append(warns, w2...)
	if len(e2) > 0 {
		reportErrors(e2, warns)
		return 2
	}

	printPlan(p)
	if len(warns) > 0 {
		section(fmt.Sprintf("⚠ 质量提醒 %d 条（不影响导入，建议审阅）", len(warns)))
		for _, w := range warns {
			fmt.Println("  · " + w)
		}
	}

	if !o.yes {
		if mode == "overwrite" {
			fmt.Print("\n  确认【题库覆盖】？请输入「覆盖」两个字后回车，直接回车取消：")
			if strings.TrimSpace(readLine(o.in)) != "覆盖" {
				fmt.Println("  已取消，题库没有改动。")
				return 0
			}
		} else {
			fmt.Print("\n  确认导入？输入 Y 回车确认，直接回车取消：")
			if strings.ToUpper(strings.TrimSpace(readLine(o.in))) != "Y" {
				fmt.Println("  已取消，题库没有改动。")
				return 0
			}
		}
	}

	backup, err := backupBank(bankDir, registryPath)
	if err != nil {
		fail("备份失败，未做任何修改：%v", err)
		return 1
	}
	fmt.Printf("\n  已备份旧题库 → %s\n", backup)

	if err := applyPlan(bankDir, p); err != nil {
		restore(backup, bankDir, registryPath)
		fail("写入失败，已从备份恢复：%v", err)
		return 1
	}
	after, err := loadBank(bankDir)
	if err == nil {
		err = selfCheck(after)
	}
	if err == nil {
		err = reg.save(registryPath)
	}
	if err != nil {
		restore(backup, bankDir, registryPath)
		fail("写入后自检失败，已从备份恢复：%v", err)
		return 1
	}
	if err := writeCatalog(catalogPath, after, concepts); err != nil {
		fmt.Printf("  ⚠ 题库已更新，但 %s 生成失败：%v\n", catalogName, err)
	}

	moved, err := archive(target, scanDir)
	if err != nil {
		fmt.Printf("  ⚠ 题库已更新，但更新文件没能移到「%s」：%v\n    请手动移走，避免下次重复导入。\n", archiveDir, err)
	} else {
		fmt.Printf("  更新文件已归档 → %s\n", moved)
		if len(p.refToID) > 0 {
			writeMapping(moved+".题号对照.txt", p)
		}
	}
	pruneBackups(filepath.Join(home, backupName))

	total := 0
	for _, c := range after {
		total += len(c.Items)
	}
	section("✅ 导入完成")
	fmt.Printf("  题库现在共 %d 题、%d 个分类；已刷新 %s。下次弹窗即生效，不用重启提醒程序。\n", total, len(after), catalogName)
	return 0
}

func applyPlan(bankDir string, p *plan) error {
	if p.mode == "overwrite" {
		entries, err := os.ReadDir(bankDir)
		if err != nil {
			return err
		}
		for _, e := range entries {
			if !e.IsDir() && strings.HasSuffix(strings.ToLower(e.Name()), ".json") {
				if err := os.Remove(filepath.Join(bankDir, e.Name())); err != nil {
					return err
				}
			}
		}
	}
	for _, cp := range p.cats {
		out, err := renderCategory(cp.cat)
		if err != nil {
			return err
		}
		if err := writeFileAtomic(filepath.Join(bankDir, cp.cat.File), out); err != nil {
			return err
		}
	}
	return nil
}

func chooseFile(files []string, o options) (string, bool) {
	if o.file != "" {
		for _, f := range files {
			if filepath.Base(f) == o.file {
				return f, true
			}
		}
		fail("没找到指定的更新文件 %s", o.file)
		return "", false
	}
	latest := files[len(files)-1]
	if len(files) == 1 || o.yes {
		return latest, true
	}
	fmt.Println("\n  发现多份更新文件：")
	for i, f := range files {
		mark := ""
		if i == len(files)-1 {
			mark = "（默认）"
		}
		fmt.Printf("    [%d] %s%s\n", i+1, filepath.Base(f), mark)
	}
	fmt.Print("  输入编号选择，直接回车用默认：")
	s := strings.TrimSpace(readLine(o.in))
	if s == "" {
		return latest, true
	}
	n, err := strconv.Atoi(s)
	if err != nil || n < 1 || n > len(files) {
		fail("编号无效")
		return "", false
	}
	return files[n-1], true
}

func chooseMode(suggested string, o options) (string, bool) {
	if o.mode != "" {
		if o.mode != "incremental" && o.mode != "overwrite" {
			fail("--mode 只能是 incremental 或 overwrite")
			return "", false
		}
		return o.mode, true
	}
	def := "incremental"
	if suggested == "overwrite" {
		def = "overwrite"
	}
	if o.yes {
		return def, true
	}
	d1, d2 := "（默认）", ""
	if def == "overwrite" {
		d1, d2 = "", "（默认）"
	}
	fmt.Println("\n  请选择导入模式：")
	fmt.Printf("    [1] 增量添加：在现有题库上新增 / 修改 / 删除%s\n", d1)
	fmt.Printf("    [2] 题库覆盖：删除现有全部分类，换成本文件的内容%s\n", d2)
	fmt.Print("  输入 1 或 2，直接回车用默认：")
	switch strings.TrimSpace(readLine(o.in)) {
	case "":
		return def, true
	case "1":
		return "incremental", true
	case "2":
		return "overwrite", true
	}
	fail("输入无效")
	return "", false
}

func reportErrors(errs, warns []string) {
	section("❌ 校验没通过（题库没有任何改动）")
	for _, e := range errs {
		fmt.Println("  · " + e)
	}
	if len(warns) > 0 {
		section("另外还有这些提醒")
		for _, w := range warns {
			fmt.Println("  · " + w)
		}
	}
	fmt.Println("\n  改好更新文件后重新双击本程序即可。")
}

func findUpdates(dir string) ([]string, error) {
	entries, err := os.ReadDir(dir)
	if err != nil {
		return nil, err
	}
	type cand struct {
		path string
		key  string
		mod  time.Time
	}
	var cs []cand
	for _, e := range entries {
		if e.IsDir() {
			continue
		}
		m := updateNameRe.FindStringSubmatch(e.Name())
		if m == nil {
			continue
		}
		seq := 0
		if m[2] != "" {
			seq, _ = strconv.Atoi(m[2])
		}
		info, _ := e.Info()
		cs = append(cs, cand{filepath.Join(dir, e.Name()), fmt.Sprintf("%s_%04d", m[1], seq), info.ModTime()})
	}
	sort.Slice(cs, func(i, j int) bool {
		if cs[i].key != cs[j].key {
			return cs[i].key < cs[j].key
		}
		return cs[i].mod.Before(cs[j].mod)
	})
	out := make([]string, len(cs))
	for i, c := range cs {
		out[i] = c.path
	}
	return out, nil
}

func archive(path, scanDir string) (string, error) {
	dir := filepath.Join(scanDir, archiveDir)
	if err := os.MkdirAll(dir, 0755); err != nil {
		return "", err
	}
	base := filepath.Base(path)
	dst := filepath.Join(dir, base)
	if _, err := os.Stat(dst); err == nil {
		ext := filepath.Ext(base)
		dst = filepath.Join(dir, strings.TrimSuffix(base, ext)+"_"+time.Now().Format("150405")+ext)
	}
	return dst, os.Rename(path, dst)
}

// ───────────────────────────── 工具函数 ─────────────────────────────

func readLine(r *bufio.Reader) string {
	if r == nil {
		return ""
	}
	s, _ := r.ReadString('\n')
	return s
}

func exeFolder() string {
	p, err := os.Executable()
	if err != nil {
		wd, _ := os.Getwd()
		return wd
	}
	if r, err := filepath.EvalSymlinks(p); err == nil {
		p = r
	}
	return filepath.Dir(p)
}

// 相对路径一律相对 exe 所在文件夹，方便整个文件夹搬家
func absFrom(base, p string) string {
	if filepath.IsAbs(p) {
		return filepath.Clean(p)
	}
	return filepath.Join(base, p)
}

func loadConfig(dir string) config {
	var c config
	data, err := os.ReadFile(filepath.Join(dir, configName))
	if err != nil {
		return c
	}
	if err := json.Unmarshal(bytes.TrimPrefix(data, []byte("\xef\xbb\xbf")), &c); err != nil {
		fmt.Printf("  ⚠ %s 格式不对，已忽略：%v\n", configName, err)
	}
	return c
}

func describeJSONErr(data []byte, err error) string {
	var se *json.SyntaxError
	var te *json.UnmarshalTypeError
	off := int64(-1)
	if errors.As(err, &se) {
		off = se.Offset
	} else if errors.As(err, &te) {
		off = te.Offset
	}
	if off < 0 {
		return err.Error()
	}
	line := 1 + bytes.Count(data[:min(int(off), len(data))], []byte("\n"))
	return fmt.Sprintf("%v（大约第 %d 行）。常见原因：少了逗号、多了结尾逗号、引号没配对、字符串里用了没转义的英文双引号", err, line)
}

func idLess(a, b string) bool { return a < b }

func contains(xs []string, s string) bool {
	for _, x := range xs {
		if x == s {
			return true
		}
	}
	return false
}

func firstNonEmpty(xs ...string) string {
	for _, x := range xs {
		if strings.TrimSpace(x) != "" {
			return x
		}
	}
	return ""
}

func clip(s string, n int) string {
	r := []rune(s)
	if len(r) <= n {
		return s
	}
	return string(r[:n-1]) + "…"
}

func sortStrings(xs []string) { sort.Strings(xs) }
