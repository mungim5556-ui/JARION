package system

import (
	"net"
	"strings"
)

// physicalMACs 는 루프백/가상 인터페이스를 뺀 MAC 주소 목록 (AA:BB:CC:DD:EE:FF 형식).
func physicalMACs() []string {
	ifaces, err := net.Interfaces()
	if err != nil {
		return nil
	}
	var out []string
	for _, i := range ifaces {
		if i.Flags&net.FlagLoopback != 0 || len(i.HardwareAddr) != 6 {
			continue
		}
		out = append(out, strings.ToUpper(i.HardwareAddr.String()))
	}
	return out
}
