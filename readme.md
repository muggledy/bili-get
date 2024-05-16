# Bilibili视频下载器

使用方式（demo）：

```console
(python39) C:\Users\muggledy\Downloads>bili-get https://www.bilibili.com/video/BV1CY4y1F7hP
output: C:\Users\muggledy\Downloads
  (origin url):https://www.bilibili.com/video/BV1CY4y1F7hP
       (title):p1_总耗时近一年！七爷带你一步到位看完昭和《奥特曼》系列全部345集怪兽及宇宙人们！_1初代奥特曼
        (desc):此视频送给希望一气看完昭和全奥的朋友们！
(episodes num):7
     (quality):清晰 480P(id:32), 流畅 360P(id:16)
selected download quality(MAX):32
start to download p1(video:清晰 480P,852x480,avc1.64001F_581618_29.412) from https://www.bilibili.com/video/BV1CY4y1F7hP/?p=1...
100.00%|████████████████████| 下载完成【application/octet-stream】 84.96MB/84.96MB
start to download p1(audio)...
100.00%|████████████████████| 下载完成【application/octet-stream】 28.28MB/28.28MB
ffmpeg merge success, save into C:\Users\muggledy\Downloads\bili_output\BV1CY4y1F7hP\p1_总耗时近一年！七爷带你一步到位看完昭和《奥特曼》系列全部345集怪兽及宇宙人们！_1初代奥特曼.mp4
Note: this is a multi-episode video, you can download them all at once with --playlist
```

- 默认是下载到当前工作路径，可以通过`-o`或`--output`指定输出目录，不存在则自动创建，譬如`bili-get https://www.bilibili.com/video/BV1CY4y1F7hP -o D:\workspace\bilibili`。这会在`--output`目录下产生两个文件夹：`bili_tmp/`和`bili_output/`，前者存放一些临时文件，用于记录多剧集视频的下载进度，如果下载过程中发生中断，重新执行命令可以继续下载过程（且对于尚未合成的剧集会尝试进行合成，除非指定`--nomerge`参数），后者则是视频、音频文件的输出文件夹
- 对于多剧集视频，可以指定`--playlist`自动下载全部剧集，只要不删除对应的`bili_tmp/`临时文件，可以任意重复执行下载命令，如`bili-get https://www.bilibili.com/video/BV1CY4y1F7hP --playlist`，也不会重复下载，如果UP主新发布了剧集，则会继续下载
- `-c`或`--cookie`用于指定您的B站Cookie信息
- `-q`或`--quality`用于指定要下载的视频质量（清晰度），可选值有`MAX`（最高质量，缺省值）、`MIN`（最低质量）、`MANUAL`（手动选择视频质量）
- `--debug`用于在控制台输出全部debug日志信息，不指定该参数，也会将日志输出到`bili_tmp/log`中以备查阅
- `--force`表示强制重新下载视频
- `--nomerge`表示是否自动合成下载下来的音视频文件，默认合成，但需要提前下载`ffmpeg`工具并将其路径添加到`PATH`环境变量