# -*- coding: utf-8 -*-
"""
FinalShell 鼠标滚轮补丁 —— 一键修复
=================================
问题: TUI 程序(Claude Code 全屏模式等)在备用屏幕下,FinalShell 把鼠标滚轮翻译成 ↑/↓ 方向键,
     即使应用已通过 DECSET 1000/1002/1006 请求鼠标事件上报。

修复要点(4 处字节码替换,全部等长,不改动类文件结构):
  com/pA  lambda$addTerminalMouseListener$4
    1. 转发条件 b(MouseEvent)[需 Shift] -> X()[鼠标上报开启即转发]
    2. 方向键门控 t.b() -> !X()[仅应用未捕获鼠标时才翻译,兼容 vim/less]
  com/E5  <init>
    3. 修饰键参数: 第二次 EW.c(e) -> iconst_0  (修复原版 bug: 按钮码被污染成 68/69,应用无法识别)
    4. 日志死区 -> event.consume()            (转发后阻止本地滚动条误滚动)

用法:
  python patch_finalshell.py            # 自动定位并打补丁(幂等,已打则跳过)
  python patch_finalshell.py --check    # 只检查当前状态
  python patch_finalshell.py --restore  # 还原为原始 jar
  python patch_finalshell.py <jar路径>  # 指定 jar
  环境变量 FINALSHELL_JAR 也可指定路径

FinalShell 更新后重跑一次即可;若新版字节码结构变化,脚本会安全中止并报错,不会写坏 jar。
"""
import os, sys, glob, shutil, struct, zipfile, hashlib, platform

# ---------- 安装定位 ----------
def reg_install_locations():
    """Windows 注册表里的安装目录"""
    locs = []
    if platform.system() != 'Windows':
        return locs
    try:
        import winreg
        keys = [
            (winreg.HKEY_LOCAL_MACHINE, r'SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall'),
            (winreg.HKEY_LOCAL_MACHINE, r'SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall'),
            (winreg.HKEY_CURRENT_USER, r'SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall'),
        ]
        for root, path in keys:
            try:
                h = winreg.OpenKey(root, path)
            except OSError:
                continue
            i = 0
            while True:
                try:
                    name = winreg.EnumKey(h, i); i += 1
                except OSError:
                    break
                try:
                    sub = winreg.OpenKey(h, name)
                    disp = winreg.QueryValueEx(sub, 'DisplayName')[0]
                    loc = winreg.QueryValueEx(sub, 'InstallLocation')[0]
                except OSError:
                    continue
                if loc and 'final' in (disp or '').lower():
                    locs.append(loc)
    except Exception:
        pass
    return locs

def find_jars():
    """跨平台搜索 finalshell.jar,返回候选路径列表"""
    cands = []
    env = os.environ.get('FINALSHELL_JAR')
    if env and os.path.exists(env):
        return [env]
    sysname = platform.system()
    if sysname == 'Windows':
        for loc in reg_install_locations():
            cands += glob.glob(os.path.join(loc, 'finalshell.jar'))
        for drive in ['C:', 'D:', 'E:', 'F:']:
            for root in [rf'{drive}\Program Files', rf'{drive}\Program Files (x86)', drive + '\\']:
                cands += glob.glob(os.path.join(root, '*inal*', 'finalshell.jar'))
    elif sysname == 'Darwin':
        cands += glob.glob('/Applications/FinalShell.app/Contents/**/finalshell.jar', recursive=True)
        cands += glob.glob(os.path.expanduser('~/Applications/FinalShell.app/Contents/**/finalshell.jar'), recursive=True)
    else:
        for base in ['/opt', '/usr/share', '/usr/local', os.path.expanduser('~')]:
            cands += glob.glob(os.path.join(base, '**/finalshell.jar'), recursive=True)
    seen, out = set(), []
    for c in cands:
        c = os.path.abspath(c)
        if c not in seen and os.path.exists(c):
            seen.add(c); out.append(c)
    return out

# ---------- 常量池 ----------
def parse_cp(data):
    if data[:4] != b'\xca\xfe\xba\xbe':
        raise ValueError('不是 class 文件')
    cp_count = struct.unpack_from('>H', data, 8)[0]
    pos, cp, i = 10, {}, 1
    while i < cp_count:
        tag = data[pos]; pos += 1
        if tag == 1:
            ln = struct.unpack_from('>H', data, pos)[0]; pos += 2
            cp[i] = (1, data[pos:pos + ln]); pos += ln
        elif tag == 7:
            cp[i] = (7, struct.unpack_from('>H', data, pos)[0]); pos += 2
        elif tag in (8, 16, 19, 20):
            cp[i] = (tag, struct.unpack_from('>H', data, pos)[0]); pos += 2
        elif tag == 15:
            cp[i] = (15, data[pos:pos + 3]); pos += 3
        elif tag in (3, 4):
            cp[i] = (tag, data[pos:pos + 4]); pos += 4
        elif tag in (9, 10, 11, 12, 17, 18):
            cp[i] = (tag, struct.unpack_from('>HH', data, pos)); pos += 4
        elif tag in (5, 6):
            cp[i] = (tag, data[pos:pos + 8]); pos += 8; i += 1
        else:
            raise ValueError('未知常量池 tag %d' % tag)
        i += 1
    return pos, cp_count, cp

def utf8(s):
    b = s.encode('utf-8')
    return struct.pack('>BH', 1, len(b)) + b

# ---------- 补丁 ----------
PA_PROLOGUE = bytes.fromhex('b8087d3e2ab407f0b90a3b0100')   # lambda$addTerminalMouseListener$4 起始

def patch_pa(data):
    idx = data.find(PA_PROLOGUE)
    if idx < 0:
        raise ValueError('pA: 未找到滚轮处理方法字节码(FinalShell 版本可能已变化)')
    if data.find(PA_PROLOGUE, idx + 1) >= 0:
        raise ValueError('pA: 方法特征不唯一,已中止')
    base = idx
    def expect(off, hexstr):
        want = bytes.fromhex(hexstr)
        got = data[base + off:base + off + len(want)]
        if got != want:
            raise ValueError('pA: 偏移 +%d 校验失败(期望 %s,实际 %s)' % (off, want.hex(), got.hex()))
    expect(27, '2a'); expect(28, '2c'); expect(29, 'b6093b')
    expect(113, '2a'); expect(114, 'b407f0'); expect(117, 'b90a370100')
    out = bytearray(data)
    out[base + 28] = 0x00                                   # aload_2 -> nop
    out[base + 29:base + 32] = bytes.fromhex('b708f8')      # b(MouseEvent) -> X()
    out[base + 114:base + 117] = bytes.fromhex('b708f8')    # t.b() -> X()
    out[base + 117:base + 122] = bytes.fromhex('0482000000')  # iconst_1; ixor; nop*3 -> !X()
    return bytes(out)

def patch_e5(data):
    cp_end, cp_count, cp = parse_cp(data)
    mwe = None
    for i, e in cp.items():
        if e[0] == 7 and cp.get(e[1], (0, b''))[1] == b'java/awt/event/MouseWheelEvent':
            mwe = i; break
    if mwe is None:
        raise ValueError('E5: 常量池中缺少 MouseWheelEvent')

    pair = bytes.fromhex('2bb800232bb80023b70026')     # 两次 EW.c(e) + Eo.<init>
    if data.count(pair) != 1:
        raise ValueError('E5: 构造器特征不唯一或未找到')
    p4 = data.find(pair)
    data = data[:p4 + 4] + bytes.fromhex('03000000') + data[p4 + 8:]   # 修饰键 -> 0

    expected = bytes.fromhex('b80027c600081201b80025')  # 日志死区 21..31
    code21 = data.find(expected)
    if code21 < 0:
        raise ValueError('E5: 未找到构造器日志死区')

    new_entries = (utf8('consume') + utf8('()V')
                   + struct.pack('>BHH', 12, cp_count, cp_count + 1)
                   + struct.pack('>BHH', 10, mwe, cp_count + 2))
    mr = cp_count + 3
    out = bytearray()
    out += data[:8]
    out += struct.pack('>H', cp_count + 4)
    out += data[10:cp_end]
    out += new_entries
    body = bytearray(data[cp_end:])
    off = code21 - cp_end
    if bytes(body[off:off + 11]) != expected:
        raise ValueError('E5: 构造器字节校验失败')
    body[off:off + 11] = struct.pack('>BBH', 0x2b, 0xb6, mr) + b'\x00' * 7  # e.consume()
    out += body
    return bytes(out)

def is_patched(data_pa, data_e5):
    try:
        i = data_pa.find(PA_PROLOGUE)
        if i < 0:
            return False
        if data_pa[i + 28] != 0x00 or data_pa[i + 29:i + 32] != bytes.fromhex('b708f8'):
            return False
        return bytes.fromhex('03000000b70026') in data_e5
    except Exception:
        return False

# ---------- 流程 ----------
def sha(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''):
            h.update(b)
    return h.hexdigest()

def in_use(path):
    try:
        with open(path, 'r+b'):
            return False
    except OSError:
        return True

def rebuild(src_path, dst_path):
    src = zipfile.ZipFile(src_path, 'r')
    tmp = dst_path + '.tmp'
    with zipfile.ZipFile(tmp, 'w') as dst:
        for info in src.infolist():
            d = src.read(info.filename)
            if info.filename == 'com/pA.class':
                d = patch_pa(d)
            elif info.filename == 'com/E5.class':
                d = patch_e5(d)
            zi = zipfile.ZipInfo(info.filename, date_time=info.date_time)
            zi.compress_type = info.compress_type
            zi.external_attr = info.external_attr
            zi.internal_attr = info.internal_attr
            zi.create_system = info.create_system
            dst.writestr(zi, d)
    src.close()
    os.replace(tmp, dst_path)

def main():
    args = sys.argv[1:]
    jar = None
    for a in args:
        if not a.startswith('--') and os.path.exists(a) and a.lower().endswith('.jar'):
            jar = os.path.abspath(a)
    if jar is None:
        found = find_jars()
        if not found:
            print('[X] 未找到 finalshell.jar,请手动指定: python patch_finalshell.py <jar路径>')
            sys.exit(1)
        jar = found[0]
        if len(found) > 1:
            print('[*] 发现多个安装,使用: ' + jar)
    print('[*] 目标: ' + jar)

    backup = jar + '.orig'
    if '--restore' in args:
        if not os.path.exists(backup):
            print('[X] 找不到备份 ' + backup); sys.exit(1)
        shutil.copy2(backup, jar)
        print('[√] 已还原为原始版本'); return

    with zipfile.ZipFile(jar) as z:
        pa, e5 = z.read('com/pA.class'), z.read('com/E5.class')
    if is_patched(pa, e5):
        print('[√] 该 FinalShell 已打过补丁,无需操作')
        print('    (如需重打请先运行 --restore)')
        return
    if '--check' in args:
        print('[!] 当前为未打补丁的原始版本'); return

    if in_use(jar):
        print('[X] 文件被占用,请先完全退出 FinalShell(含托盘图标)后重试')
        sys.exit(1)

    try:
        if os.path.exists(backup):
            if sha(backup) != sha(jar):
                shutil.copy2(backup, backup + '.1')
                print('[*] 检测到版本变化,旧备份另存为 ' + backup + '.1')
                shutil.copy2(jar, backup)
                print('[+] 新版本已备份到 ' + backup)
            else:
                print('[*] 已存在同版本备份')
        else:
            shutil.copy2(jar, backup)
            print('[+] 原始 jar 已备份到 ' + backup)

        rebuild(backup, jar)
    except PermissionError:
        print('[X] 写入被拒绝: 没有管理员权限(安装目录在 Program Files 下)')
        sys.exit(2)
    except Exception as e:
        print('[X] 打补丁失败: ' + str(e))
        print('    FinalShell 版本可能不兼容(字节码特征变化),jar 未被修改')
        sys.exit(1)
    print('[√] 补丁完成: 滚轮将作为鼠标事件转发给已启用鼠标上报的 TUI 应用')
    print('    还原: python patch_finalshell.py --restore')

if __name__ == '__main__':
    main()
