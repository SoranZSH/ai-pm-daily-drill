package main

// 题库（契约②）读写、备份与恢复。

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"time"
)

type category struct {
	File       string
	Category   string
	CategoryEn string
	Domain     string
	Items      []json.RawMessage
	IDs        []string
	CRLF       bool
}

// 题目中与校验、目录、选题有关的字段
type itemInfo struct {
	ID          string      `json:"id"`
	Ref         string      `json:"ref"`
	Level       string      `json:"level"`
	Kind        string      `json:"kind"`
	Difficulty  string      `json:"difficulty"`
	Tags        []string    `json:"tags"`
	Concepts    []string    `json:"concepts"`
	Prereq      []string    `json:"prereq"`
	QCn         string      `json:"q_cn"`
	QEn         string      `json:"q_en"`
	Concept     *bilingual  `json:"concept"`
	AEn         string      `json:"a_en"`
	ACn         string      `json:"a_cn"`
	KeyPhrases  []bilingual `json:"key_phrases"`
	Approach    string      `json:"approach"`
	Tips        string      `json:"tips"`
	SourceRepos []string    `json:"source_repos"`
	Added       string      `json:"added"`
}

type bilingual struct {
	Cn string `json:"cn"`
	En string `json:"en"`
}

func infoOf(raw json.RawMessage) itemInfo {
	var it itemInfo
	json.Unmarshal(raw, &it)
	return it
}

func loadBank(dir string) ([]*category, error) {
	entries, err := os.ReadDir(dir)
	if err != nil {
		return nil, err
	}
	var out []*category
	for _, e := range entries {
		if e.IsDir() || !strings.HasSuffix(strings.ToLower(e.Name()), ".json") {
			continue
		}
		c, err := loadCategory(filepath.Join(dir, e.Name()))
		if err != nil {
			return nil, fmt.Errorf("%s：%v", e.Name(), err)
		}
		out = append(out, c)
	}
	sort.Slice(out, func(i, j int) bool { return out[i].File < out[j].File })
	return out, nil
}

func loadCategory(path string) (*category, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	data = bytes.TrimPrefix(data, []byte("\xef\xbb\xbf"))
	var raw struct {
		Category   string            `json:"category"`
		CategoryEn string            `json:"category_en"`
		Domain     string            `json:"domain"`
		Items      []json.RawMessage `json:"items"`
	}
	if err := json.Unmarshal(data, &raw); err != nil {
		return nil, err
	}
	c := &category{File: filepath.Base(path), Category: raw.Category, CategoryEn: raw.CategoryEn,
		Domain: raw.Domain, CRLF: bytes.Contains(data, []byte("\r\n"))}
	for _, r := range raw.Items {
		var b bytes.Buffer
		if json.Compact(&b, r) == nil {
			r = b.Bytes()
		}
		c.Items = append(c.Items, r)
		c.IDs = append(c.IDs, infoOf(r).ID)
	}
	return c, nil
}

// 输出格式与 Python json.dump(ensure_ascii=False, indent=2) 一致，键顺序保持原样
func renderCategory(c *category) ([]byte, error) {
	var b bytes.Buffer
	b.WriteString(`{"category":`)
	b.Write(jsonString(c.Category))
	b.WriteString(`,"category_en":`)
	b.Write(jsonString(c.CategoryEn))
	if c.Domain != "" {
		b.WriteString(`,"domain":`)
		b.Write(jsonString(c.Domain))
	}
	b.WriteString(`,"items":[`)
	for i, it := range c.Items {
		if i > 0 {
			b.WriteByte(',')
		}
		b.Write(it)
	}
	b.WriteString("]}")
	var out bytes.Buffer
	if err := json.Indent(&out, b.Bytes(), "", "  "); err != nil {
		return nil, err
	}
	out.WriteByte('\n')
	if c.CRLF {
		return bytes.ReplaceAll(out.Bytes(), []byte("\n"), []byte("\r\n")), nil
	}
	return out.Bytes(), nil
}

func writeFileAtomic(path string, data []byte) error {
	tmp := path + ".tmp"
	if err := os.WriteFile(tmp, data, 0644); err != nil {
		return err
	}
	if err := os.Rename(tmp, path); err != nil {
		os.Remove(tmp)
		return err
	}
	return nil
}

// 备份题库全部 JSON 和题号登记
func backupBank(bankDir, registryPath string) (string, error) {
	dst := filepath.Join(filepath.Dir(bankDir), backupName, time.Now().Format("20060102-150405"))
	if _, err := os.Stat(dst); err == nil {
		dst += "_" + fmt.Sprint(time.Now().UnixNano()%1000)
	}
	if err := os.MkdirAll(dst, 0755); err != nil {
		return "", err
	}
	entries, err := os.ReadDir(bankDir)
	if err != nil {
		return "", err
	}
	for _, e := range entries {
		if e.IsDir() || !strings.HasSuffix(strings.ToLower(e.Name()), ".json") {
			continue
		}
		if err := copyFile(filepath.Join(bankDir, e.Name()), filepath.Join(dst, e.Name())); err != nil {
			return "", err
		}
	}
	if _, err := os.Stat(registryPath); err == nil {
		regDir := filepath.Join(dst, "_登记")
		os.MkdirAll(regDir, 0755)
		if err := copyFile(registryPath, filepath.Join(regDir, filepath.Base(registryPath))); err != nil {
			return "", err
		}
	}
	return dst, nil
}

func restore(backup, bankDir, registryPath string) {
	cur, _ := os.ReadDir(bankDir)
	for _, e := range cur {
		if !e.IsDir() && strings.HasSuffix(strings.ToLower(e.Name()), ".json") {
			if _, err := os.Stat(filepath.Join(backup, e.Name())); errors.Is(err, os.ErrNotExist) {
				os.Remove(filepath.Join(bankDir, e.Name()))
			}
		}
	}
	entries, _ := os.ReadDir(backup)
	for _, e := range entries {
		if !e.IsDir() {
			copyFile(filepath.Join(backup, e.Name()), filepath.Join(bankDir, e.Name()))
		}
	}
	reg := filepath.Join(backup, "_登记", filepath.Base(registryPath))
	if _, err := os.Stat(reg); err == nil {
		copyFile(reg, registryPath)
	} else {
		os.Remove(registryPath)
	}
}

func pruneBackups(root string) {
	entries, err := os.ReadDir(root)
	if err != nil {
		return
	}
	var dirs []string
	for _, e := range entries {
		if e.IsDir() {
			dirs = append(dirs, e.Name())
		}
	}
	sort.Strings(dirs)
	for len(dirs) > keepBackups {
		os.RemoveAll(filepath.Join(root, dirs[0]))
		dirs = dirs[1:]
	}
}

func copyFile(src, dst string) error {
	in, err := os.Open(src)
	if err != nil {
		return err
	}
	defer in.Close()
	out, err := os.Create(dst)
	if err != nil {
		return err
	}
	if _, err := io.Copy(out, in); err != nil {
		out.Close()
		return err
	}
	return out.Close()
}

// 写入后自检：题号唯一、前置可解析、拓展题有基础前置
func selfCheck(cats []*category) error {
	seen := map[string]string{}
	infos := map[string]itemInfo{}
	for _, c := range cats {
		for _, raw := range c.Items {
			it := infoOf(raw)
			if it.ID == "" {
				return fmt.Errorf("%s 有题目缺少 id", c.File)
			}
			if f, ok := seen[it.ID]; ok {
				return fmt.Errorf("题号 %s 同时出现在 %s 和 %s", it.ID, f, c.File)
			}
			seen[it.ID] = c.File
			infos[it.ID] = it
		}
	}
	for id, it := range infos {
		hasF := false
		for _, p := range it.Prereq {
			if _, ok := infos[p]; !ok {
				return fmt.Errorf("%s 的前置题 %s 不存在", id, p)
			}
			if levelOfID(p) == "F" {
				hasF = true
			}
		}
		if levelOfID(id) == "X" && !hasF {
			return fmt.Errorf("拓展题 %s 没有基础题前置", id)
		}
	}
	if cyc := findCycle(infos); cyc != "" {
		return fmt.Errorf("前置关系出现循环：%s", cyc)
	}
	return nil
}
