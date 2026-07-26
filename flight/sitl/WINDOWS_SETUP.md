# Windows 侧准备（需要管理员权限的部分）

> 这一份里的操作 **Kiro 做不了**，必须你本人执行。原因：需要管理员权限，且要重启。
> 其余部分（`.wslconfig`、引导脚本、代码）已经全部准备好。
>
> 本机实测状态（2026-07-27，`METAMECHBOOK01`）：
>
> | 项 | 值 |
> |---|---|
> | 系统 | Windows 11 家庭版，Build 26200 |
> | 内存 / 核心 | 31.3 GB / 16 逻辑核心 |
> | C 盘可用 | 1196 GB |
> | 固件虚拟化 | ✅ `HypervisorPresent = True`（已启用，不用进 BIOS） |
> | WSL | ❌ **未安装** |
> | `.wslconfig` | ✅ 已由 Kiro 生成于 `C:\Users\Klara\.wslconfig` |
>
> 家庭版可以正常跑 WSL2，不需要专业版。

---

## 第 1-3 步：✅ 已完成（2026-07-27，Kiro 代做）

**本机已全部装好，第 1-3 步可跳过。** 而且有个意外收获：**没有重启 Windows**。

### 实际执行与结果

| 项 | 结果 |
|---|---|
| `VirtualMachinePlatform` | **本来就已启用**（省了一半工作） |
| `Microsoft-Windows-Subsystem-Linux` | Disabled → **Enabled**（带 `-NoRestart`，未自动重启） |
| WSL 版本 | **2.7.11.0**，内核 `6.18.33.2-microsoft-standard-WSL2` |
| WSLg | **1.0.73.2**（图形支持在，Gazebo 界面可用） |
| Direct3D 层 | `1.611.1`（AMD 显卡在 WSL 里的加速通道） |
| 发行版 | **Ubuntu 22.04.5 LTS**，VERSION=**2** |
| Linux 用户 | `klara`（uid 1000），已设为默认登录用户 |
| 用户组 | `sudo adm dialout video plugdev` |
| sudo | 已配 NOPASSWD |
| systemd | **running**（PID 1 = systemd） |
| `.wslconfig` 生效 | ✅ `nproc`=12、内存 19Gi、swap 8.0Gi，与配置一致 |

### 为什么不用重启 Windows

`Microsoft-Windows-Subsystem-Linux` 这个可选功能主要服务 **WSL1**。
本项目只需要 **WSL2**，而 WSL2 依赖的是 `VirtualMachinePlatform` —— 那个在本机**原本就已启用**。

所以现在的状态是：
- ✅ WSL2 完全可用，Ubuntu 22.04 已在跑
- ⚠️ WSL1 暂不可用（`wsl --status` 会提示「当前计算机配置不支持 WSL1」）—— **不影响本项目**
- 系统有待重启标记，但**你可以在任何方便的时候重启**，不必为了继续工作而重启

### 两处踩坑与修正（已修，记录备查）

**坑 1：`.wslconfig` 里两个键放错了段。**
`autoMemoryReclaim` 与 `sparseVhd` 原先被放在 `[wsl2]` 段，WSL 2.7.11 启动时报
「`wsl2.autoMemoryReclaim ... 未知`」「`wsl2.sparseVhd ... 未知`」。
这两个键属于 **`[experimental]`** 段。已移正，警告消失。

**坑 2：账号创建用非交互方式，避免阻塞。**
安装时用了 `--no-launch`，所以首次运行的交互式建账号流程没跑。
改为 `useradd` 非交互创建，并把密码留空（锁定）+ 配置 NOPASSWD sudo。

> **关于 NOPASSWD sudo 的安全性**：在 WSL 下这不降低安全性 —— 任何能在 Windows 上执行
> `wsl -u root` 的人本来就已经能无密码拿到 root。想设密码随时 `sudo passwd klara`。

`dialout` 组是有意加的（以后接 6C 串口要用），`video` 组也是（Gazebo 渲染要用）。

### 换机器时怎么重做

```powershell
# 管理员 PowerShell
wsl --install --no-launch -d Ubuntu-22.04    # --no-launch 避免弹交互式建账号提示
# 若 VirtualMachinePlatform 未启用，此步之后需要重启 Windows

# 非管理员，创建账号（把 klara 换成你的名字）
wsl -d Ubuntu-22.04 -u root -- useradd -m -s /bin/bash -G sudo,adm,dialout,plugdev,video klara
wsl -d Ubuntu-22.04 -u root -- bash -c 'echo "klara ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/90-skylark-klara && chmod 0440 /etc/sudoers.d/90-skylark-klara'
wsl -d Ubuntu-22.04 -u root -- bash -c 'printf "[user]\ndefault=klara\n\n[boot]\nsystemd=true\n" > /etc/wsl.conf'
wsl --shutdown
```

---

## 第 4 步：确认版本与图形支持

```powershell
wsl --list --verbose
```

期望输出（`VERSION` 必须是 2）：

```
  NAME            STATE           VERSION
* Ubuntu-22.04    Running         2
```

图形支持（Gazebo 要用）测试，在 WSL 里：

```bash
sudo apt update && sudo apt install -y x11-apps
xclock          # 应该弹出一个时钟窗口
```

弹出来就说明 WSLg 正常。这台机器是 AMD 显卡，Gazebo 的渲染兜底方案已经写进
`bootstrap_wsl2.sh`（会自动探测并按需设置 `MESA_D3D12_DEFAULT_ADAPTER_NAME` 或
`LIBGL_ALWAYS_SOFTWARE`）。

---

## 第 5 步：交给自动化脚本

到这里 Windows 侧就完了。剩下的全部由脚本处理：

```bash
cd /mnt/c/Users/Klara/Desktop/PX4/skylark/flight/sitl

bash bootstrap_wsl2.sh --check      # 先只检查环境，不装任何东西
bash bootstrap_wsl2.sh              # 确认无误后全量安装
```

首次全量安装约 **40-60 分钟**，大部分时间在下载和编译，可以放着不管。它会装：

| 组件 | 版本 | 说明 |
|---|---|---|
| PX4-Autopilot | v1.17.0 | 递归 clone 含子模块，约 1.5-2 GB |
| PX4 工具链 + Gazebo Harmonic | — | 由 PX4 官方 `Tools/setup/ubuntu.sh` 装 |
| ROS 2 Humble | desktop 完整版 | 约 2 GB |
| Micro XRCE-DDS Agent | v2.4.3 | 从源码编译 |
| px4_msgs | release/1.17 | **必须与固件版本严格对应** |
| px4_ros_com | main | 官方 offboard 示例 |

脚本是**幂等**的 —— 网络中断后直接重跑，已完成的步骤会跳过。

版本号全部来自 `flight/VERSIONS.md`，那是唯一权威来源。

---

## 第 6 步：跑起来

```bash
cd /mnt/c/Users/Klara/Desktop/PX4/skylark/flight/sitl
bash run_sitl.sh                    # 自动开 tmux 三面板
# 图形卡的话： bash run_sitl.sh --headless
```

验证接口契约已注册（在 tmux 第 3 个面板）：

```bash
ros2 topic list | grep /fmu/
ros2 interface list | grep skylark
ros2 interface show skylark_flight_msgs/action/InspectSweep
```

跑官方 offboard 示例：

```bash
ros2 run px4_ros_com offboard_control
```

**这一步跑通 = S1 阶段正式开始。**

---

## 一个磁盘位置的建议

上面用的是 `/mnt/c/...`（直接访问 Windows 文件系统），好处是代码在 Windows 侧可以用
IDE 编辑、git 操作也在 Windows 侧统一管理。

**代价是 I/O 慢** —— WSL2 跨文件系统访问 `/mnt/c` 比原生 ext4 慢一个数量级。
`colcon build` 会明显感觉到。

`bootstrap_wsl2.sh` 的处理方式：
- PX4 源码、ROS 2 工作区建在 **WSL 原生路径** `~/PX4-Autopilot`、`~/skylark_ws`（快）
- Skylark 自有的 ROS 2 包通过**软链**从 `/mnt/c/...` 链进 `~/skylark_ws/src`（改代码不用来回拷）

这样编译在原生文件系统上跑，源码仍在 Windows 侧受 git 管理。如果编译还是慢到不能忍，
再考虑把整个仓库 clone 到 WSL 内部，代价是要在两侧各维护一份 git remote。

---

## 出问题时

| 症状 | 原因与处置 |
|---|---|
| `wsl --install` 报权限错误 | PowerShell 没有以管理员身份运行 |
| 重启后 `wsl` 仍说未安装 | Windows 功能未启用成功。用管理员 PowerShell 跑 `Get-WindowsOptionalFeature -Online -FeatureName VirtualMachinePlatform` 看状态 |
| `free -h` 显示 31 GB | `.wslconfig` 没生效。确认路径 `C:\Users\Klara\.wslconfig` 且无 `.txt` 扩展名，然后 `wsl --shutdown` |
| `xclock` 不弹窗 | WSLg 异常。`wsl --update` 然后 `wsl --shutdown` |
| `colcon build` 报 empy 错误 | `pip install -U 'empy==3.3.4'`。PX4 对 empy 版本敏感，3.4+ 会失败 |
| **apt 报 `packages.ros.org` 证书主机名不匹配** | **上游服务端问题，非本机故障。** `bootstrap_wsl2.sh` 已自动把 ROS 源改成 `http://` 绕过，见下方说明 |
| `colcon build` 被 OOM kill | `colcon build --parallel-workers 1`，或提高 `.wslconfig` 的 `memory` |
| 脚本报 `bad interpreter: ...^M` | 行尾问题。仓库已加 `.gitattributes` 强制 `*.sh` 为 LF，若仍出现执行 `dos2unix <文件>` |
| WSL 占用磁盘一直涨 | `.wslconfig` 已开 `sparseVhd=true`。手动回收：`wsl --shutdown` 后用 `diskpart` 的 `compact vdisk` |

---

## 已知的上游问题：`packages.ros.org` 证书主机名不匹配

2026-07-27 实测发现，记录在此以免日后误判为本机故障。

**现象**：

```
curl: (60) SSL: no alternative certificate subject name matches target host name 'packages.ros.org'
```

**实测数据**（Windows 侧与 WSL 侧结果完全一致，故排除 WSL 特有因素）：

| 项 | 值 |
|---|---|
| 收到的证书 subject | `CN=*.osuosl.org, O=Oregon State University, S=Oregon, C=US` |
| 证书 issuer | `CN=InCommon RSA Server CA 2, O=Internet2, C=US` |
| 证书 SAN | 仅 `*.osuosl.org`、`osuosl.org` —— **不含 `packages.ros.org`** |
| 证书有效期 | 2025-07-17 ~ 2026-08-18（证书本身有效，只是主机名不匹配） |
| `http://packages.ros.org/ros2/ubuntu/dists/jammy/InRelease` | **HTTP 200，可达** |

OSUOSL（俄勒冈州立大学开源实验室）是 ROS 软件源的**合法官方托管方**，所以我们连到的是
真服务器，只是它对 `packages.ros.org` 这个主机名没有配对应证书。**这是服务端配置问题。**

**处置**：`bootstrap_wsl2.sh` 会自动把 ROS apt 源从 `https://` 改成 `http://`。

**为什么用 http 是安全的**：

apt 的完整性保障来自 `InRelease` 文件的 **GPG 签名**（密钥来自官方 `ros2-apt-source` 包），
不是来自 TLS。TLS 在这里只提供**保密性**（隐藏「你在下载哪些包」），不提供完整性。
被篡改的包会因签名校验失败而被 apt 拒绝安装。Debian/Ubuntu 官方源默认也是 http，原理相同。

**若上游修好了**：把 `bootstrap_wsl2.sh` 里那段 `sed` 改 http 的循环删掉即可（脚本内有注释标注）。

---

## 与 6C 硬件的关系

**第 1-6 步全部不需要 6C 插上。** S1 纯软 SITL 阶段用不到真机。

6C 的首次上电是**独立的一条线**（约 1 小时，也不需要机架/电池/遥控）：
刷 v1.17.0 → 全套校准 → 导出 `.params` 基线 → 登记到 `flight/params/CHANGELOG.md`。
清单见 `flight/params/CHANGELOG.md` 的「首次导出的前置动作」。

两条线可以并行，互不依赖。
