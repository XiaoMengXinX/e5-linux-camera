# E5 Linux camera modules

为e5、lym10k和t512n构建与运行中kernel配置匹配的arm64相机模块：`sprd_sensor.ko`、`sprd_flash_drv.ko`和`sprd_camera.ko`。

## 源码与配置

`source/camera`采用实机使用的vendor camera移植源码，保留sensor、flash driver、camera system及其共享headers。camera system选择qogirn6l适配（使用qogirn6pro实现），CSI选择receiver_r3p2。sensor保留由CONFIG_COMPAT控制的compat实现。

E5常亮补光由固件提供的`e5-aw3641-torch`模块管理，通过`/sys/class/leds/e5:white:torch/brightness`接受`0`（关闭）和`1`（开启）。相机模块包保留`sprd_flash_drv`，提供`sprd_camera`依赖的vendor flash接口；AW3641硬件由系统LED驱动控制。E5构建配置启用`CONFIG_LEDS_E5_AW3641=m`，与上游新版固件一致。拍照同步的高亮闪光模式尚未实现。

源码沿革包含Motorola UNISOC camera的`4d7aa697120fedbe4b8d0a238ff6b4fed3d0c747`、Enceka/kernel_sprd_ums9158的`283a1a9e409d005e155fccab1031da13166b2950`及针对Linux6.18的移植，原有copyright与license声明保留。驱动及本仓库构建脚本遵循GPL-2.0-only，见[LICENSE](LICENSE)。

`configs/e5.config`、`configs/lym10k.config`和`configs/t512n.config`是对应机型实机导出的完整配置。lym10k启用CONFIG_COMPAT，e5和t512n禁用。构建不替换成defconfig，不改变debug/BTF配置；只在发布模块副本中移除debug和BTF sections。

## 构建

GitHub Actions在每次branch push和workflow_dispatch时使用原生`ubuntu-24.04-arm`。resolve job先获取[kanoqwq/e5-linux](https://github.com/kanoqwq/e5-linux)当前main，从`tools/build-layout.json`的`local_kernel_build.revision`读取固定baseline，将driver、board、kernel commits保存为同次运行的snapshot。三个matrix job各自取这份snapshot，并行构建一个profile。全部成功后，独立publish job收集归档、再次核对snapshot并统一发布。发布仅在默认分支进行。

每种机型使用独立kernel worktree，执行上游`devices/<profile>/prepare-kernel.py`，以LLVM18和`RUSTC=false`运行`olddefconfig`、`modules_prepare`以及完整`vmlinux modules`构建，生成匹配headers和Module.symvers后再编译三个外部模块。当前实机配置未启用Rust，固定探测结果以保持原配置；olddefconfig后的归一化配置指纹必须与实机配置一致，否则在完整编译前报告具体差异。上游prepare可能下载其固定commit和checksum约束的板级适配源码。任何下载、配置、编译或校验失败都会终止发布。

在Ubuntu24.04 arm64环境中，从仓库根目录执行：

```sh
sudo bash scripts/install-deps.sh
python3 -m unittest discover -s tests -v
python3 scripts/prepare.py
python3 scripts/build.py e5
python3 scripts/build.py lym10k
python3 scripts/build.py t512n
```

`prepare.py`要求仓库已有commit，用其记录driver_commit；支持`--board-ref <ref>`固定board版本、`--resolve-only`仅解析snapshot、`--snapshot <inputs.json>`严格复用已解析版本。`work/`保存本次运行的源码和objects，`dist/`保存归档及构建记录；再次构建应使用新的work目录。可通过`--work`、`--dist`指定路径。`build.py --configure-only`仅执行上游prepare和配置阶段，CI通过`--stage configure/kernel/modules`分别执行三个阶段。

完整kernel缓存只保存每个profile的objects目录。精确key包括kernel/board commits、完整输入config和olddefconfig后config的SHA256、实际toolchain及已安装package版本、构建脚本摘要、固定Kbuild时间与source/objects路径。每次先重新prepare并生成候选config，命中后校验provenance、有效config及vmlinux、Module.symvers和关键headers/checksums，直接跳过modules_prepare和vmlinux/modules。source文件mtime固定到baseline commit时间，避免fresh checkout触发依赖更新。缓存未命中时完整构建，成功后立即保存，再编译外部模块；校验失败直接报错。

所有阶段使用`CC='ccache clang-18'`。ccache按profile隔离，设置CCACHE_BASEDIR、NOHASHDIR和固定KBUILD_BUILD_TIMESTAMP，不改动config。每个profile上限256MB，在新snapshot保存成功后删除同profile同branch的旧ccache snapshot。完整kernel objects缓存也按profile和branch只保留当前有效key，避免源码或配置变化后旧的约1GB缓存持续占用配额。维持GitHub默认10GB总额度；workflow输出objects、vmlinux、ccache占用及剩余磁盘空间。

## Release协议

固定tag为`modules`。每个运行包命名为：

```text
sprd-camera-{profile}-{kernel_release}-arm64.tar.gz
```

归档根目录包含：

```text
manifest.json
modules/sprd_sensor.ko
modules/sprd_flash_drv.ko
modules/sprd_camera.ko
```

LVGL安装端校验profile、kernel_release、config_sha256及SHA256后，将模块放入`/usr/libexec/e5-infoscreen/camera`，由UI按需通过finit_module加载。模块依赖顺序为sensor、flash、camera，卸载顺序相反。

全局索引asset名为`manifest.json`，格式如下：

```json
{
  "schema": 1,
  "builds": [
    {
      "profile": "lym10k",
      "kernel_release": "6.18.54-lym10k-bringup1",
      "asset": "sprd-camera-lym10k-6.18.54-lym10k-bringup1-arm64.tar.gz",
      "sha256": "<archive SHA256>",
      "config_sha256": "<effective config SHA256>",
      "modules": {
        "sprd_sensor.ko": "<module SHA256>",
        "sprd_flash_drv.ko": "<module SHA256>",
        "sprd_camera.ko": "<module SHA256>"
      },
      "driver_commit": "<camera repository commit>",
      "kernel_commit": "<Linux baseline commit>",
      "board_commit": "<e5-linux main commit>"
    }
  ]
}
```

包内manifest是对应的同一个entry，增加`schema: 1`并省略归档自身的`sha256`字段。

config_sha256针对构建后`.config`：取匹配`CONFIG_[A-Za-z0-9_]+=.*`的有效赋值行，排除以下七个工具链元数据key，按整行排序，以LF连接并保留最后一个LF，然后计算SHA256。`# CONFIG_* is not set`及普通注释不参与；其他所有有效值均保留。

```text
CONFIG_CC_VERSION_TEXT
CONFIG_CLANG_VERSION
CONFIG_LLD_VERSION
CONFIG_GCC_VERSION
CONFIG_AS_VERSION
CONFIG_LD_VERSION
CONFIG_PAHOLE_VERSION
```

三种profile全部成功且归档校验通过后，发布器读取旧索引，按`profile + kernel_release`合并；相同key覆盖，其他entry与asset保留。首次发布先创建draft，上传三个归档，再上传全局manifest，最后公开release。后续发布同样最后上传manifest。有效config、输入config摘要及source/toolchain记录另存Actions artifact。

所有运行共享concurrency队列，`cancel-in-progress: false`。发布器同时检查默认分支HEAD及release body中的run编号，拒绝旧commit或较旧run覆盖已发布结果。首次接管已有release时，要求已有本发布器的run marker；缺少marker或旧索引异常时直接失败，需维护者检查。

GitHub Release不提供多asset事务：更新已有同名归档与最终索引之间存在短暂窗口，网络中断也可能留下部分asset已更新的状态。安装端应以索引为准验证SHA256，校验失败时保留原安装。维护者可重跑当前commit恢复一致性。构建阶段失败不会上传Release资产。
