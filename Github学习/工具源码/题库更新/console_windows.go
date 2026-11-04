//go:build windows

package main

import "syscall"

// 让 Windows 控制台按 UTF-8 显示中文
func setupConsole() {
	k := syscall.NewLazyDLL("kernel32.dll")
	k.NewProc("SetConsoleOutputCP").Call(65001)
	k.NewProc("SetConsoleCP").Call(65001)
}
