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

## 第 1 步：装 WSL2 + Ubuntu 22.04

**以管理员身份**打开 PowerShell（开始菜单搜 PowerShell → 右键 → 以管理员身份运行），执行：

```powershell
wsl --install --no-launch -d Ubuntu-22.04
```

`--no-launch` 是有意的：让它只安装不启动，避免安装过程中弹出交互式的账号创建提示。

这一步会自动启用两个 Windows 功能（`Microsoft-Windows-Subsystem-Linux` 与
`VirtualMachinePlatform`），然后下载 Ubuntu 22.04（约 500 MB）。

### 然后重启电脑

启用 Windows 功能必须重启才生效。这一步不能跳。

---

## 第 2 步：创建 Linux 账号

重启后，普通（非管理员）PowerShell 里执行：

```powershell
wsl
```

首次进入会提示创建账号：

```
Enter new UNIX username:   ← 建议就用 klara（全小写，Linux 习惯）
New password:              ← 输入时不显示字符，正常现象
Retype new password:
```

这个密码是 WSL 内部 `sudo` 用的，与 Windows 账号无关。**记住它**，后面装依赖要用。

---

## 第 3 步：确认 `.wslconfig` 生效

```powershell
exit                  # 退出 WSL
wsl --shutdown        # 关闭 WSL 虚拟机，让 .wslconfig 生效
wsl                   # 重新进入
```

进去之后验证：

```bash
free -h    # 应显示约 20 GB 内存（不是 31 GB）
nproc      # 应显示 12（不是 16）
```

对不上说明 `.wslconfig` 没生效，检查文件路径是否为 `C:\Users\Klara\.wslconfig`
且**没有扩展名**（Windows 资源管理器可能隐藏了 `.txt`）。

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
| `colcon build` 被 OOM kill | `colcon build --parallel-workers 1`，或提高 `.wslconfig` 的 `memory` |
| 脚本报 `bad interpreter: ...^M` | 行尾问题。仓库已加 `.gitattributes` 强制 `*.sh` 为 LF，若仍出现执行 `dos2unix <文件>` |
| WSL 占用磁盘一直涨 | `.wslconfig` 已开 `sparseVhd=true`。手动回收：`wsl --shutdown` 后用 `diskpart` 的 `compact vdisk` |

---

## 与 6C 硬件的关系

**第 1-6 步全部不需要 6C 插上。** S1 纯软 SITL 阶段用不到真机。

6C 的首次上电是**独立的一条线**（约 1 小时，也不需要机架/电池/遥控）：
刷 v1.17.0 → 全套校准 → 导出 `.params` 基线 → 登记到 `flight/params/CHANGELOG.md`。
清单见 `flight/params/CHANGELOG.md` 的「首次导出的前置动作」。

两条线可以并行，互不依赖。
