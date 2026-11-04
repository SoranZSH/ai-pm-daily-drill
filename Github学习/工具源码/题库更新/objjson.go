package main

// 保持键顺序的 JSON 对象：用于在不打乱原有字段顺序的前提下修改题目（改 id、改 prereq、加 added）。

import (
	"bytes"
	"encoding/json"
	"fmt"
)

type kv struct {
	k string
	v json.RawMessage
}

type object []kv

func parseObject(raw []byte) (object, error) {
	dec := json.NewDecoder(bytes.NewReader(raw))
	dec.UseNumber()
	tok, err := dec.Token()
	if err != nil {
		return nil, err
	}
	if d, ok := tok.(json.Delim); !ok || d != '{' {
		return nil, fmt.Errorf("不是 JSON 对象")
	}
	var o object
	for dec.More() {
		t, err := dec.Token()
		if err != nil {
			return nil, err
		}
		key, ok := t.(string)
		if !ok {
			return nil, fmt.Errorf("键不是字符串")
		}
		var v json.RawMessage
		if err := dec.Decode(&v); err != nil {
			return nil, err
		}
		o = append(o, kv{key, v})
	}
	return o, nil
}

func (o object) get(k string) (json.RawMessage, bool) {
	for _, p := range o {
		if p.k == k {
			return p.v, true
		}
	}
	return nil, false
}

func (o object) has(k string) bool {
	_, ok := o.get(k)
	return ok
}

// set 替换已有键的值（保持位置），没有则追加到末尾。
func (o *object) set(k string, v json.RawMessage) {
	for i := range *o {
		if (*o)[i].k == k {
			(*o)[i].v = v
			return
		}
	}
	*o = append(*o, kv{k, v})
}

// rename 把键 old 改名为 nw 并赋新值，位置不变；old 不存在则在开头插入。
func (o *object) rename(old, nw string, v json.RawMessage) {
	for i := range *o {
		if (*o)[i].k == old {
			(*o)[i] = kv{nw, v}
			return
		}
	}
	*o = append(object{{nw, v}}, (*o)...)
}

func (o *object) del(k string) {
	out := (*o)[:0]
	for _, p := range *o {
		if p.k != k {
			out = append(out, p)
		}
	}
	*o = out
}

func (o object) marshal() json.RawMessage {
	var b bytes.Buffer
	b.WriteByte('{')
	for i, p := range o {
		if i > 0 {
			b.WriteByte(',')
		}
		b.Write(jsonString(p.k))
		b.WriteByte(':')
		var c bytes.Buffer
		if err := json.Compact(&c, p.v); err == nil {
			b.Write(c.Bytes())
		} else {
			b.Write(p.v)
		}
	}
	b.WriteByte('}')
	return b.Bytes()
}

func jsonString(s string) []byte {
	var b bytes.Buffer
	enc := json.NewEncoder(&b)
	enc.SetEscapeHTML(false)
	enc.Encode(s)
	return bytes.TrimRight(b.Bytes(), "\n")
}

func jsonStrings(xs []string) json.RawMessage {
	var b bytes.Buffer
	b.WriteByte('[')
	for i, x := range xs {
		if i > 0 {
			b.WriteByte(',')
		}
		b.Write(jsonString(x))
	}
	b.WriteByte(']')
	return b.Bytes()
}
