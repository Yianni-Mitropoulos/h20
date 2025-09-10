#!/usr/bin/env bash
set -euo pipefail

sudo tee -a /etc/sysctl.d/50-hardening.conf > /dev/null &lt;&lt;'EOF'
################################
#### MEMORY/DEBUG/FORENSICS ####
################################
kernel.kptr_restrict = 2             # Hide kernel pointers everywhere
kernel.dmesg_restrict = 1            # Only root can read dmesg
kernel.yama.ptrace_scope = 3         # Completely disable ptrace except direct child
kernel.sysrq = 0                     # No magic sysrq
kernel.ftrace_enabled = 0            # Block kernel tracing (anti-forensics)
kernel.perf_event_paranoid = 3       # No perf monitoring for non-root
kernel.perf_event_mlock_kb = 1       # Minimal perf event buffer
kernel.kexec_load_disabled = 1       # No kexec (rootkits/forensics)
kernel.kprobes_allow_uds = 0         # No unprivileged kprobes (if supported)
kernel.core_pattern = "|/bin/false"  # Never dump core to disk
kernel.core_pipe_limit = 0           # No core dump pipes
kernel.randomize_va_space = 2        # Full ASLR
vm.mmap_min_addr = 65536             # Block low-address mmap attacks
vm.compact_unevictable_allowed = 0   # Prevent compaction of sensitive data
kernel.numa_balancing = 0            # Disable page migration/auto NUMA

#######################
#### SWAP BEHAVIOR ####
#######################
vm.swappiness = 10             # Do not use swap except under a lot of ram pressure
vm.overcommit_memory = 2       # Strict overcommit restrictions (reduce DoS/fuzz)
vm.overcommit_ratio = 400      # Gives a 400% overcommit ratio
vm.dirty_background_ratio = 7  # Reduced from a default of 10
vm.dirty_ratio = 15            # Reduced from a default of 20
vm.page-cluster = 4            # 64KiB swap clusters seems reasonable
vm.min_free_kbytes = 65536     # Extra RAM for kernel (resist memory starvation)

###########################
#### HIDE PROCESS INFO ####
###########################
kernel.pid_max = 4194304
kernel.ngroups_max = 65536
kernel.threads-max = 32768
kernel.sched_child_runs_first = 1

#######################################
#### ANTI-SURVEILLANCE / ANTI-LEAK ####
#######################################
kernel.printk = 3 3 3 3      # Reduces kernel logging verbosity - good for minimizing leakage into dmesg, journald, or serial consoles
kernel.nmi_watchdog = 0      # Disables kernel NMI watchdog - reduces noise and can prevent info leakage via debugging/traps
kernel.acpi_video_flags = 0  # Minimal ACPI logs
kernel.acpi_rsdp = 0         # Minimal ACPI root system desc
kernel.domainname = ""       # Removes legacy NIS/YP domain - safe, modern systems do not need it
# kernel.hostname = ""       # If this was a bare-metal Debian box, you would uncomment this. But within Qubes it creates problems, and should remain commented

###########################
#### FILESYSTEM / MISC ####
###########################
fs.suid_dumpable = 0         # No setuid core dumps
fs.protected_regular = 2     # Block regular file hardening attacks
fs.protected_symlinks = 1    # Block symlink privilege attacks
fs.protected_hardlinks = 1   # Block hardlink privilege attacks
fs.protected_fifos = 1       # Block FIFO tricks
fs.protected_readdir = 1     # Block dangerous readdir tricks (newer kernels)
fs.inode_readahead_blks = 8  # Minimal readahead
fs.pipe-user-pages-soft = 0  # Harden pipe attacks

###################################
#### USERNAMESPACES/CONTAINERS ####
###################################
kernel.unprivileged_userns_clone = 0  # Block userns (most privesc)
kernel.unprivileged_bpf_disabled = 1  # Block unprivileged BPF everywhere
user.max_user_namespaces = 0          # No user namespaces for any process
user.max_mnt_namespaces = 8
user.max_pid_namespaces = 8
user.max_net_namespaces = 8
user.max_uts_namespaces = 8
user.max_ipc_namespaces = 8
user.max_cgroup_namespaces = 8
user.max_time_namespaces = 8

####################################
#### AUDIT/LOGGING MINIMIZATION ####
####################################
kernel.audit_enabled = 0     # No kernel audit (if using forensics resistance)
kernel.random.trust_cpu = 0  # Do not trust CPU for randomness

######################
#### MISC PRIVACY ####
######################
dev.tty0.autoclose = 1  # Autoclose on logout (no stray processes)
dev.tty.autoclose = 1

####################################
#### MAXIMIZE MEMORY RANDOMNESS ####
####################################
vm.mmap_rnd_bits = 32         # Maximum mmap entropy (if arch supports)
vm.mmap_rnd_compat_bits = 16  # Same for compat mode

########################################
#### ACCOMODATE HARDENED ALLOCATORS ####
########################################
vm.max_map_count = 1048576  # Multiply default value by 16x to support extra guard pages

#################################
#### NETWORK STACK HARDENING ####
#################################
# IPv4
net.ipv4.tcp_timestamps = 0
net.ipv4.conf.all.rp_filter = 1
net.ipv4.conf.default.rp_filter = 1
net.ipv4.conf.all.accept_source_route = 0
net.ipv4.conf.default.accept_source_route = 0
net.ipv4.conf.all.accept_redirects = 0
net.ipv4.conf.default.accept_redirects = 0
net.ipv4.conf.all.secure_redirects = 1
net.ipv4.conf.default.secure_redirects = 1
net.ipv4.conf.all.send_redirects = 0
net.ipv4.conf.default.send_redirects = 0
net.ipv4.conf.all.log_martians = 1
net.ipv4.conf.default.log_martians = 1
net.ipv4.icmp_echo_ignore_broadcasts = 1
net.ipv4.icmp_ignore_bogus_error_responses = 1
net.ipv4.tcp_syncookies = 1
net.ipv4.conf.all.shared_media = 0
net.ipv4.conf.default.shared_media = 0
net.ipv4.conf.all.proxy_arp = 0
net.ipv4.conf.default.proxy_arp = 0
net.ipv4.ip_forward = 0
net.ipv4.conf.all.arp_filter = 1
net.ipv4.conf.default.arp_filter = 1
net.ipv4.conf.all.arp_announce = 2
net.ipv4.conf.default.arp_announce = 2
net.ipv4.conf.all.arp_ignore = 2
net.ipv4.conf.default.arp_ignore = 2

# IPv6
net.ipv6.conf.all.disable_ipv6 = 1
net.ipv6.conf.default.disable_ipv6 = 1
net.ipv6.conf.lo.disable_ipv6 = 1
net.ipv6.conf.all.accept_ra = 0
net.ipv6.conf.default.accept_ra = 0
net.ipv6.conf.all.accept_redirects = 0
net.ipv6.conf.default.accept_redirects = 0
net.ipv6.conf.all.accept_source_route = 0
net.ipv6.conf.default.accept_source_route = 0
net.ipv6.conf.all.drop_unsolicited_na = 1
net.ipv6.conf.default.drop_unsolicited_na = 1
net.ipv6.conf.lo.drop_unsolicited_na = 1
EOF

echo "Success!"
echo "Hardened /etc/sysctl.d/20-hardening.conf written."