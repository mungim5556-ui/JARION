//go:build !windows

package service

import (
	"context"
	"errors"
)

var errWindowsOnly = errors.New("서비스 등록은 Windows 에서만 가능합니다. 'run' 으로 실행하세요")

func IsService() bool                            { return false }
func RunService(func(ctx context.Context)) error { return errWindowsOnly }
func Install(string) error                       { return errWindowsOnly }
func Uninstall() error                           { return errWindowsOnly }
