package main

// 题号登记：记录每个「领域-层级」用过的最大序号，序号永不回收。

import (
	"bytes"
	"encoding/json"
	"os"
	"path/filepath"
	"regexp"
	"strconv"
	"strings"
	"time"
)

var (
	idV2Re     = regexp.MustCompile(`^([A-Z]{2,4})-([FX])(\d{3})$`)
	idLegacyRe = regexp.MustCompile(`^[A-Z]{2,6}-\d{3}$`)
)

type registry struct {
	Version int            `json:"version"`
	Max     map[string]int `json:"max"`
	Updated string         `json:"updated"`
}

// levelOfID：新格式题号返回 F/X；旧格式题号一律按基础题处理
func levelOfID(id string) string {
	if m := idV2Re.FindStringSubmatch(id); m != nil {
		return m[2]
	}
	return "F"
}

// 读题号登记；文件不存在时从当前题库与全部备份重建（rebuilt=true）
func loadRegistry(path, bankDir string) (*registry, bool) {
	r := &registry{Version: 1, Max: map[string]int{}}
	data, err := os.ReadFile(path)
	if err == nil {
		data = bytes.TrimPrefix(data, []byte("\xef\xbb\xbf"))
		if json.Unmarshal(data, r) == nil && r.Max != nil {
			return r, false
		}
		r = &registry{Version: 1, Max: map[string]int{}}
	}
	// 重建
	scan := func(dir string) {
		cats, err := loadBank(dir)
		if err != nil {
			return
		}
		for _, c := range cats {
			r.observe(c.IDs)
		}
	}
	scan(bankDir)
	backups := filepath.Join(filepath.Dir(bankDir), backupName)
	if entries, err := os.ReadDir(backups); err == nil {
		for _, e := range entries {
			if e.IsDir() {
				scan(filepath.Join(backups, e.Name()))
				// 备份里的旧登记也参与取最大值
				var old registry
				if d, err := os.ReadFile(filepath.Join(backups, e.Name(), "_登记", filepath.Base(path))); err == nil {
					if json.Unmarshal(bytes.TrimPrefix(d, []byte("\xef\xbb\xbf")), &old) == nil {
						for k, v := range old.Max {
							if v > r.Max[k] {
								r.Max[k] = v
							}
						}
					}
				}
			}
		}
	}
	return r, true
}

func (r *registry) observe(ids []string) {
	for _, id := range ids {
		if m := idV2Re.FindStringSubmatch(id); m != nil {
			n, _ := strconv.Atoi(m[3])
			key := m[1] + "-" + m[2]
			if n > r.Max[key] {
				r.Max[key] = n
			}
		}
	}
}

// next 分配下一个题号（调用前应已 observe 当前题库）
func (r *registry) next(domain, level string) string {
	key := domain + "-" + level
	r.Max[key]++
	return key + pad3(r.Max[key])
}

func pad3(n int) string {
	s := strconv.Itoa(n)
	for len(s) < 3 {
		s = "0" + s
	}
	return s
}

func (r *registry) save(path string) error {
	r.Updated = time.Now().Format("2006-01-02T15:04:05")
	keys := make([]string, 0, len(r.Max))
	for k := range r.Max {
		keys = append(keys, k)
	}
	sortStrings(keys)
	var b strings.Builder
	b.WriteString("{\n  \"version\": 1,\n  \"max\": {")
	for i, k := range keys {
		if i > 0 {
			b.WriteString(",")
		}
		b.WriteString("\n    " + string(jsonString(k)) + ": " + strconv.Itoa(r.Max[k]))
	}
	if len(keys) > 0 {
		b.WriteString("\n  ")
	}
	b.WriteString("},\n  \"updated\": " + string(jsonString(r.Updated)) + "\n}\n")
	return writeFileAtomic(path, []byte(b.String()))
}
