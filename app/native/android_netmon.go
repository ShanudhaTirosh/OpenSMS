// Copyright (c) Tailscale Inc & OpenSMS AUTHORS
// SPDX-License-Identifier: BSD-3-Clause

//go:build android

package main

import (
	"errors"
	"net"
	"net/netip"
	"time"

	"tailscale.com/net/netmon"
	_ "tailscale.com/feature/androiddns"
)

func init() {
	netmon.RegisterInterfaceGetter(androidInterfaces)
}

func androidInterfaces() ([]netmon.Interface, error) {
	// Query standard net.Interfaces if permitted (e.g. Android < 11 or privileged)
	ifs, err := net.Interfaces()
	if err == nil && len(ifs) > 0 {
		ret := make([]netmon.Interface, len(ifs))
		for i := range ifs {
			ret[i].Interface = &ifs[i]
		}
		return ret, nil
	}

	// Fallback for Android 11+ (API 30+) unprivileged sandbox where netlinkrib is denied:
	// Discover local outbound source IP via UDP routing (does not send packets, allowed in sandbox).
	var addrs []net.Addr
	if ip, ok := discoverOutboundIP("udp4", "8.8.8.8:53"); ok {
		addrs = append(addrs, &net.IPNet{IP: ip.AsSlice(), Mask: net.CIDRMask(32, 32)})
	}
	if ip, ok := discoverOutboundIP("udp6", "[2001:4860:4860::8888]:53"); ok {
		addrs = append(addrs, &net.IPNet{IP: ip.AsSlice(), Mask: net.CIDRMask(128, 128)})
	}
	if len(addrs) == 0 {
		return nil, errors.New("android: no outbound network routes found")
	}

	return []netmon.Interface{{
		Interface: &net.Interface{
			MTU:   1500,
			Name:  "android",
			Flags: net.FlagUp | net.FlagRunning,
		},
		AltAddrs: addrs,
	}}, nil
}

func discoverOutboundIP(network, addr string) (netip.Addr, bool) {
	d := net.Dialer{Timeout: 2 * time.Second}
	c, err := d.Dial(network, addr)
	if err != nil {
		return netip.Addr{}, false
	}
	defer c.Close()
	ua, ok := c.LocalAddr().(*net.UDPAddr)
	if !ok {
		return netip.Addr{}, false
	}
	ip, ok := netip.AddrFromSlice(ua.IP)
	if !ok {
		return netip.Addr{}, false
	}
	ip = ip.Unmap()
	if ip.IsLoopback() || ip.IsUnspecified() {
		return netip.Addr{}, false
	}
	return ip, true
}
