# Bilibili视频下载器

<a alt="null">![](https://img.shields.io/badge/python-3.6+-green)&nbsp;![](https://img.shields.io/badge/platform-Windows%20%7C%20Linux-pink)&nbsp;<a href="https://pypi.org/project/sole-bili-get/" alt="null"><img src="https://img.shields.io/github/v/release/muggledy/bili-get"/></a></a>

## 下载

### 方式一

```console
pip install sole-bili-get -i https://www.pypi.org/simple/
```

PS（更新版本）：`pip install sole-bili-get -U`

### 方式二

```console
git clone https://github.com/muggledy/bili-get.git
python setup.py sdist bdist_wheel
pip install dist\sole_bili_get-0.0.1-py3-none-any.whl //demo
bili-get --help
```

## 使用

```console
C:\Users\muggledy\Downloads>bili-get https://www.bilibili.com/video/BV1CY4y1F7hP
output: C:\Users\muggledy\Downloads
  (origin url):https://www.bilibili.com/video/BV1CY4y1F7hP
       (title):p1_总耗时近一年！七爷带你一步到位看完昭和《奥特曼》系列全部345集怪兽及宇宙人们！_1初代奥特曼
        (desc):此视频送给希望一气看完昭和全奥的朋友们！
(episodes num):7
     (quality):清晰 480P(id:32), 流畅 360P(id:16)
selected download quality(MAX):32
get danmu urls success for 7 episodes
p1 danmu xml file is downloaded into C:\Users\muggledy\Downloads\bili_output\BV1CY4y1F7hP\p1_总耗时近一年！七爷带你一步到位看完昭和《奥特曼》系列全部345集怪兽及宇宙人们！_1初代奥特曼.xml
start to download p1(video:清晰 480P,852x480,avc1.64001F_581618_29.412) from https://www.bilibili.com/video/BV1CY4y1F7hP/?p=1...
100.00%|████████████████████| 下载完成【application/octet-stream】 84.96MB/84.96MB
start to download p1(audio)...
100.00%|████████████████████| 下载完成【application/octet-stream】 28.28MB/28.28MB
ffmpeg merge success, save into C:\Users\muggledy\Downloads\bili_output\BV1CY4y1F7hP\p1_总耗时近一年！七爷带你一步到位看完昭和《奥特曼》系列全部345集怪兽及宇宙人们！_1初代奥特曼.mp4
Note: this is a multi-episode video, you can download them all at once with --playlist
```

- 默认是下载到当前工作路径，可以通过`-o`或`--output`指定输出目录，不存在则自动创建，譬如`bili-get https://www.bilibili.com/video/BV1CY4y1F7hP -o D:\workspace\bilibili`。这会在`--output`目录下产生两个文件夹：`bili_tmp/`和`bili_output/`，前者存放一些临时文件，用于记录多剧集视频的下载进度，如果下载过程中发生中断，重新执行命令可以继续下载过程（且对于尚未合成的剧集会尝试进行合成，除非指定`--nomerge`参数），后者则是视频、音频、封面、弹幕文件的输出文件夹

- 对于多剧集视频，可以指定`--playlist`自动下载全部剧集，只要不删除对应的`bili_tmp/`临时文件，可以任意重复执行下载命令，如`bili-get https://www.bilibili.com/video/BV1CY4y1F7hP --playlist`，也不会重复下载，如果UP主新发布了剧集，则会继续下载

- `-c`或`--cookie`用于指定您的B站Cookie信息，这样就可以下载1080P视频了

  ```console
  C:\Users\muggledy\Downloads>bili-get https://www.bilibili.com/video/BV1CY4y1F7hP -c "your cookie"
  output: C:\Users\muggledy\Downloads
    (origin url):https://www.bilibili.com/video/BV1CY4y1F7hP
         (title):p1_总耗时近一年！七爷带你一步到位看完昭和《奥特曼》系列全部345集怪兽及宇宙人们！_1初代奥特曼
          (desc):此视频送给希望一气看完昭和全奥的朋友们！
  (episodes num):7
       (quality):高清 1080P(id:80), 高清 720P(id:64), 清晰 480P(id:32), 流畅 360P(id:16)
  selected download quality(MAX):80
  get danmu urls success for 7 episodes
  p1 danmu xml file is downloaded into C:\Users\muggledy\Downloads\bili_output\BV1CY4y1F7hP\p1_总耗时近一年！七爷带你一步到位看完昭和《奥特曼》系列全部345集怪兽及宇宙人们！_1初代奥特曼.xml
  start to download p1(video:高清 1080P,1920x1080,avc1.640032_2344634_29.412) from https://www.bilibili.com/video/BV1CY4y1F7hP/?p=1...
  100.00%|████████████████████| 下载完成【video/mp4】 342.48MB/342.48MB
  start to download p1(audio)...
  100.00%|████████████████████| 下载完成【video/mp4】 28.28MB/28.28MB
  ffmpeg merge success, save into C:\Users\muggledy\Downloads\bili_output\BV1CY4y1F7hP\p1_总耗时近一年！七爷带你一步到位看完昭和《奥特曼》系列全部345集怪兽及宇宙人们！_1初代奥特曼.mp4
  Note: this is a multi-episode video, you can download them all at once with --playlist
  ```

  Cookie获取方式如下：

  ![B站cookie获取方式](https://raw.githubusercontent.com/muggledy/bili-get/master/bilibili_cookie.jpg)

  注：如果是Windows平台使用Chrome浏览器，可以指定`-c`参数为`chrome`，程序将自动从`./AppData/Local/Google/Chrome/User Data/default/Network/Cookies`读取B站的Cookie信息，譬如我们可以通过`bili-get https://www.bilibili.com/video/BV18G411D7FM -c chrome`命令下载1080p视频

- `-q`或`--quality`用于指定要下载的视频质量（清晰度），可选值有`MAX`（最高质量，缺省值）、`MIN`（最低质量）、`MANUAL`（手动选择视频质量）

- `--nomerge`表示是否自动合成下载下来的音视频文件，默认合成，但需要提前下载[ffmpeg](https://ffmpeg.org/download.html)工具（如[windows版本](https://www.gyan.dev/ffmpeg/builds/)）并将其路径添加到`PATH`环境变量

- `--force`表示强制重新下载视频，如果没有指定`--playlist`参数，则只是重新下载当前剧集，否则会直接删除`bili_tmp/`临时文件，重新下载全部剧集，但不会立即删除全部已下载音视频文件，而是覆盖更新

- `--debug`用于在控制台输出全部debug日志信息，不指定该参数，也会将日志输出到`bili_tmp/download.log`中以备查阅

- 默认随视频会下载封面图片

- 默认随视频会下载弹幕XML文件，可以使用[danmu2ass](https://github.com/ikde/danmu2ass)做弹幕格式转换，双击Danmu2Ass.sln，用Visual Studio打开并编译，在项目Danmu2Ass目录下会生成bin文件夹，进入其中的Debug文件夹，可以看到一个Kaedei.Danmu2Ass.exe可执行文件，将视频和弹幕文件一块拖动到该可执行文件图标上去即可生成ASS字幕文件，再通过[potplayer](https://potplayer.daum.net/)打开视频即可自动加载字幕

## 致谢

如果觉得本工具有用，请点个Star呗~，有bug或有改进意见请提issue，thx！