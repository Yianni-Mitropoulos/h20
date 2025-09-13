#!/usr/bin/env bash
set -euo pipefail

echo "Creating /etc/sysctl.d/20-base-hardening.conf"
sudo tee /etc/sysctl.d/20-base-hardening.conf > /dev/null <<'EOF'
fs.inode_readahead_blks = 8  # Minimal readahead
fs.pipe-user-pages-soft = 0  # Harden pipe attacks
fs.protected_fifos = 1       # Block FIFO tricks
fs.protected_hardlinks = 1   # Block hardlink privilege attacks
fs.protected_regular = 2     # Block regular file hardening attacks
fs.protected_symlinks = 1    # Block symlink privilege attacks
fs.suid_dumpable = 0         # No setuid core dumps
kernel.audit_enabled = 1              # Enable kernel audits; improves intrusion detection, weakens forensics resistance
kernel.core_pattern = "|/bin/false"   # Never dump core to disk
kernel.core_pipe_limit = 0            # No core dump pipes
kernel.dmesg_restrict = 1             # Only root can read dmesg
kernel.domainname = ""                # Removes legacy NIS/YP domain - safe, modern systems do not need it
kernel.ftrace_enabled = 0             # Block kernel tracing (anti-forensics)
# kernel.hostname = ""                  # If this was a bare-metal Debian box, you would uncomment this. But within Qubes it creates problems, and should remain commented
kernel.hotplug = ""                   # Make sure no legacy hotplug helper is used
kernel.kexec_load_disabled = 1        # No kexec (rootkits/forensics)
kernel.kptr_restrict = 2              # Hide kernel pointers everywhere
kernel.modprobe = ""                  # Disable kernel module autoload (no UMH)
kernel.ngroups_max = 65536            # Allow many supplementary groups (compat tweak; minimal security impact)
kernel.nmi_watchdog = 0               # Disables kernel NMI watchdog - reduces noise and can prevent info leakage via debugging/traps
kernel.numa_balancing = 0             # Disable page migration/auto NUMA
kernel.perf_event_mlock_kb = 1        # Minimal perf event buffer
kernel.perf_event_paranoid = 3        # No perf monitoring for non-root
kernel.pid_max = 4194304              # Large PID space to reduce PID reuse predictability (trade: slight kernel memory)
kernel.printk = 4 4 1 7               # Detail logs. Improves intrusion detection, but not ideal for forensics resistance
kernel.randomize_va_space = 2         # Full ASLR
kernel.random.trust_cpu = 0           # Do not trust CPU for randomness
kernel.sched_child_runs_first = 1     # Minor scheduling tweak; no direct security effect (keeps fork/exec behavior predictable)
kernel.sysrq = 0                      # No magic sysrq
kernel.threads-max = 32768            # Cap system threads to limit fork/thread DoS
kernel.unprivileged_bpf_disabled = 1  # Block unprivileged BPF everywhere
kernel.unprivileged_userns_clone = 0  # Block userns (most privesc)
kernel.yama.ptrace_scope = 3          # Completely disable ptrace except direct child
net.ipv4.conf.all.accept_redirects = 0          # Ignore ICMP redirects to prevent MITM route injection
net.ipv4.conf.all.accept_source_route = 0       # Block LSRR/SSRR (source routing) to prevent spoofed paths
net.ipv4.conf.all.arp_announce = 2              # Strong ARP announcements; reduce ARP spoofing/leakage
net.ipv4.conf.all.arp_filter = 1                # ARP replies only on the correct interface to limit spoofing
net.ipv4.conf.all.arp_ignore = 2                # Only reply to ARP if target IP is local and on the incoming interface
net.ipv4.conf.all.log_martians = 1              # Log suspicious (martian) packets for awareness
net.ipv4.conf.all.proxy_arp = 0                 # Disable proxy ARP to avoid acting as unintended gateway
net.ipv4.conf.all.rp_filter = 1                 # Reverse path filtering to block spoofed source addresses
net.ipv4.conf.all.secure_redirects = 1          # Only accept redirects from gateways (defense in depth; disabled anyway by accept_redirects=0)
net.ipv4.conf.all.send_redirects = 0            # Do not send ICMP redirects (avoid leaking topology)
net.ipv4.conf.all.shared_media = 0              # Treat interfaces as non-shared to tighten ARP/ND behavior
net.ipv4.conf.default.accept_redirects = 0      # Same as above for future interfaces
net.ipv4.conf.default.accept_source_route = 0   # Same as above for future interfaces
net.ipv4.conf.default.arp_announce = 2          # Same as above for future interfaces
net.ipv4.conf.default.arp_filter = 1            # Same as above for future interfaces
net.ipv4.conf.default.arp_ignore = 2            # Same as above for future interfaces
net.ipv4.conf.default.log_martians = 1          # Same as above for future interfaces
net.ipv4.conf.default.proxy_arp = 0             # Same as above for future interfaces
net.ipv4.conf.default.rp_filter = 1             # Same as above for future interfaces
net.ipv4.conf.default.secure_redirects = 1      # Same as above for future interfaces (defense in depth)
net.ipv4.conf.default.send_redirects = 0        # Same as above for future interfaces
net.ipv4.conf.default.shared_media = 0          # Same as above for future interfaces
net.ipv4.icmp_echo_ignore_broadcasts = 1        # Drop broadcast pings (smurf attack mitigation)
net.ipv4.icmp_ignore_bogus_error_responses = 1  # Ignore bogus ICMP errors
net.ipv4.ip_forward = 0                         # Not a router (prevents unintended forwarding)
net.ipv4.tcp_syncookies = 1                     # SYN cookies to mitigate SYN flood
net.ipv4.tcp_timestamps = 0                     # Disable TCP timestamps to reduce info leakage (trade: RTT estimation)
net.ipv6.conf.all.accept_ra = 0                # Do not accept router advertisements (host should not auto-configure routes)
net.ipv6.conf.all.accept_redirects = 0         # Ignore IPv6 redirects to avoid MITM
net.ipv6.conf.all.accept_source_route = 0      # Block IPv6 source routing
net.ipv6.conf.all.disable_ipv6 = 1             # Disable IPv6 entirely if not used (reduce attack surface)
net.ipv6.conf.all.drop_unsolicited_na = 1      # Drop unsolicited Neighbor Advertisements (spoofing defense)
net.ipv6.conf.default.accept_ra = 0            # Same as above for future interfaces
net.ipv6.conf.default.accept_redirects = 0     # Same as above for future interfaces
net.ipv6.conf.default.accept_source_route = 0  # Same as above for future interfaces
net.ipv6.conf.default.disable_ipv6 = 1         # Same as above for future interfaces
net.ipv6.conf.default.drop_unsolicited_na = 1  # Same as above for future interfaces
net.ipv6.conf.lo.disable_ipv6 = 1              # Disable IPv6 on loopback (maximal reduction of IPv6 surface)
net.ipv6.conf.lo.drop_unsolicited_na = 1       # Drop unsolicited NA on loopback
user.max_cgroup_namespaces = 8  # Limit cgroup namespaces to constrain namespace abuse
user.max_ipc_namespaces = 8     # Limit IPC namespaces to constrain isolation abuse
user.max_mnt_namespaces = 8     # Limit mount namespaces (mitigate container-style privesc tricks)
user.max_net_namespaces = 8     # Limit network namespaces to prevent runaway creation
user.max_pid_namespaces = 8     # Limit PID namespaces to constrain process isolation abuse
user.max_time_namespaces = 8    # Limit time namespaces (reduce resource exhaustion vectors)
user.max_user_namespaces = 0    # No user namespaces for any process
user.max_uts_namespaces = 8     # Limit UTS namespaces (hostname/domain isolation abuse)
vm.compact_unevictable_allowed = 0  # Prevent compaction of sensitive data
vm.dirty_background_ratio = 7       # Reduced from a default of 10
vm.dirty_ratio = 15                 # Reduced from a default of 20
vm.max_map_count = 1048576          # Multiply default value by 16x to support extra guard pages
vm.min_free_kbytes = 65536          # Extra RAM for kernel (resist memory starvation)
vm.mmap_min_addr = 65536            # Block low-address mmap attacks
vm.mmap_rnd_bits = 32               # Maximum mmap entropy (if arch supports)
vm.mmap_rnd_compat_bits = 16        # Same for compat mode
EOF

echo "Creating /etc/sysctl.d/50-overrides.conf"
sudo tee /etc/sysctl.d/50-overrides.conf > /dev/null <<'EOF'
# [ipv4-multiple-connections] Allow simultaneous network connections (e.g. WiFi + Ethernet) over IPv4.
# net.ipv4.conf.all.rp_filter = 2

# [ipv6] Allow IPv6 connections.
# net.ipv6.conf.all.disable_ipv6 = 0
# net.ipv6.conf.default.disable_ipv6 = 0
# net.ipv6.conf.lo.disable_ipv6 = 0

# [ipv6-loopback] Allow IPv6 loopback (may help with Chrome/Chromium/VSCode/PostgreSQL issues).
# net.ipv6.conf.lo.disable_ipv6 = 0

# [userns] Allow user namespaces (used by Chrome/Chromium/VSCode/Docker/Flatpack/Snap, etc.)
# kernel.unprivileged_userns_clone = 0

# [modprobe] Allow the kernel to load non-blacklisted kernel modules as needed.
# kernel.modprobe=/sbin/modprobe

# [reduced-logging] Disables a lot of logging.
# kernel.audit_enabled = 0
# kernel.printk = 3 3 3 3               
EOF

echo "Success!"
echo "Hardened /etc/sysctl.d/ settings written. Edit the override file as per your needs."