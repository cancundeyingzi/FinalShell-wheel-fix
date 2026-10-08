# FinalShell 鼠标滚轮补丁

## 解决的问题

在 FinalShell 中使用 TUI 程序(Claude Code 全屏模式、vim、htop 等)时,鼠标滚轮被翻译成 ↑/↓ 方向键。

根本原因:FinalShell(基于 xterm 备用屏幕滚轮模式)在应用切换到备用屏幕(alt screen)后,把滚轮事件一律翻译成方向键发送给远端。即使应用(如 Claude Code 全屏模式)已经通过 `ESC[?1000h` / `ESC[?1006h` 请求了鼠标事件上报,FinalShell 也只在按住 **Shift** 时才把滚轮作为鼠标事件转发——这与 xterm 标准行为(应用捕获鼠标时滚轮直接发给应用)正好相反。

## 补丁效果

| 场景 | 原版行为 | 补丁后 |
|---|---|---|
| 应用启用鼠标上报(Claude Code 全屏/tmux mouse) | 滚轮 → ↑/↓ 方向键(错误) | 滚轮 → SGR 鼠标事件,**可原生滚动对话** |
| 应用未启用鼠标上报的备用屏幕(vim/less/htop) | 滚轮 → ↑/↓ 方向键 | 不变(保持 xterm alternateScroll 兼容行为) |
| 普通终端回滚 | 滚动 FinalShell 滚动条 | 不变 |

## 技术细节

对 `finalshell.jar` 中两个类做等长字节码替换(Allatori 混淆,均为同长度替换,不改类文件结构):

**`com/pA` — `lambda$addTerminalMouseListener$4`(滚轮处理器)**
- 转发条件 `b(MouseEvent)`(需 Shift)→ `X()`(鼠标上报开启即转发)
- 方向键翻译分支条件 `t.b()` → `!X()`(仅应用未捕获鼠标时才翻译)

**`com/E5`(滚轮事件包装器)**
- 构造器中的死代码日志调用 → `event.consume()`(转发后阻止事件冒泡到本地滚动条)
- **修复 FinalShell 原版 bug**:E5 把按钮码(4/5)同时当作修饰键传给 EC,`IR.u()` 里 `btn |= C()` 会把按钮码污染成 68/69,远端应用无法识别为滚轮(标准应为 SGR 64/65、X10 96/97)。补丁将修饰键参数改为 0。这解释了为什么原版 Shift+滚轮转发功能从未正常工作过。

## 一键使用

**方式 A(推荐):双击运行**
- `fix-wheel.bat` —— 自动定位 FinalShell 安装并打补丁;已打过则提示无需操作;权限不足会提示用管理员身份运行;打完自动复查状态
- `restore-wheel.bat` —— 一键还原为官方原版

脚本会自动查找 Python(系统 python → py 启动器 → 常见安装路径)。Windows 下 FinalShell 装在 `Program Files (x86)` 时,补丁写入需要**管理员权限**,右键"以管理员身份运行"即可。

**方式 B:命令行**
```bash
python patch_finalshell.py            # 自动定位并打补丁(幂等)
python patch_finalshell.py --check    # 仅检查状态
python patch_finalshell.py --restore  # 还原
python patch_finalshell.py <jar路径>  # 指定 jar
```
也支持环境变量 `FINALSHELL_JAR` 指定路径。脚本跨平台:Windows 查注册表 + Program Files,macOS 找 `/Applications/FinalShell.app`,Linux 找 `/opt`、`/usr/share` 等。

**方式 C:其他设备没有 Python**
若两台设备 FinalShell 版本一致,直接把本机已打补丁的 `finalshell.jar`(在 `D:\Program Files (x86)\finalshell\`)复制到目标机器同名目录覆盖即可;版本不一致则装个 Python 跑方式 A/B 最省事。

### FinalShell 更新后

自动更新会覆盖 `finalshell.jar`,补丁失效。重新双击 `fix-wheel.bat` 即可:
1. 检测到 jar 内容变化 → 自动把旧备份另存为 `finalshell.jar.orig.1`,为新版重新备份
2. 用新备份重新打补丁
3. 若新版混淆结构变化导致字节特征不匹配,脚本会**安全中止并报错**,不会写坏 jar

### 其他注意事项
- 打补丁前请完全退出 FinalShell(脚本会检测文件占用并拒绝执行)
- 补丁基于字节特征定位而非固定偏移,FinalShell 小版本更新通常仍可匹配

## 注意事项

1. **FinalShell 自动更新后补丁会失效**,重新运行一次脚本即可(若新版混淆结构变化,脚本会安全中止并报错,不会写坏 jar)。
2. 打补丁前请先关闭 FinalShell(运行中的 jar 无法覆盖)。
3. 若在 Claude Code 中滚轮仍不生效,说明 Claude Code 未启用鼠标捕获,可在服务器上设置 `~/.claude/settings.json` 确认处于全屏 TUI 模式(`/tui fullscreen`),或直接用经典模式(对话留在普通终端缓冲,滚轮滚动 FinalShell 回滚)。
4. 本补丁仅修改上述 3 处字节码,未触碰授权/网络/配置逻辑。
