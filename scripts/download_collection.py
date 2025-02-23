import sole_bili_get, requests, json, datetime, argparse, os, time
from pathlib import Path

'''
视频合集解析和自动下载
1. 按照合集视频列表顺序下载
2. 秉持尽力交付原则，如果合集中的部分视频下载失败，请勿重复执行该脚本造成重复下载覆盖，应手动下载那些失败的视频
3. 脚本成功运行前提是事先安装了sole_bili_get模块（pip install sole-bili-get）
4. 合集自动下载脚本的运行：
   python download_collection.py <url>
   demo url: https://www.bilibili.com/video/BV1cS421w7yh
'''

def get_video_collection(url, **kwargs):
    req = requests.get(url, headers={'User-Agent':
'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36', 
'Referer':'https://www.bilibili.com/'}, cookies=None)
    if req.ok:
        match_json = sole_bili_get.utils.find_json_dict_from_text(req.text, "ugc_season", 1)
        if not match_json:
            print(f'Error: can\'t find "ugc_season" in responded html')
            return
        match_json = json.loads(match_json[0])
        print(f'标题：{match_json["title"]}')
        print(f'封面：{match_json["cover"]}')
        episodes = match_json["sections"][0]["episodes"]
        print(f'全集：{len(episodes)}集')
        download_failed_list = []
        for i, e in enumerate(episodes, 1):
            print(f'{i}. {e["title"]}')
            #sub_url = f'https://www.bilibili.com/video/{sole_bili_get.av2bv.av2bv(int(e["aid"]))}'
            sub_url = f'https://www.bilibili.com/video/{e["bvid"]}'
            print(f'  链接：{sub_url}')
            print(f'  时长：{e["arc"]["duration"]/60:.4}分钟')
            print(f'  图片：{e["arc"]["pic"]}')
            print(f'  作者：{e["arc"]["author"]["name"]}')
            author_homepage = f'https://space.bilibili.com/{e["arc"]["author"]["mid"]}'
            print(f'  空间：{author_homepage}')
            print(f'  统计：{int(e["arc"]["stat"]["view"])/10000:.5}万(播放量)、{e["arc"]["stat"]["danmaku"]}(弹幕数)、{e["arc"]["stat"]["like"]}(点赞数)、'
                  f'{e["arc"]["stat"]["coin"]}(投币数)、{e["arc"]["stat"]["fav"]}(收藏量)、{e["arc"]["stat"]["share"]}(分享)、{e["arc"]["stat"]["reply"]}(评论数)')
            print(f'  发布：{datetime.datetime.fromtimestamp(e["arc"]["pubdate"])}')
            bilibili = sole_bili_get.Bilibili(sub_url, disable_console_log=True, 
            fetch_playlists=False, quality='MAX', force_re_download=False, base_dir=kwargs.get('output'), 
            auto_merge=True, ffmpeg_debug=False, 
            remove_merge_materials=True, debug_all=False, headers={}, cookies=kwargs.get('cookies'), multi_thread_num=3)
            bilibili.start()
            bilibili.clear_crawler_thread_pool_resource()
            download_info = bilibili.get_current_downloaded_info()
            #print(download_info)
            if (download_info[0] != download_info[1]):
                download_failed_list.append((i, sub_url))
        if download_failed_list:
            print('以下剧集下载失败（请使用bili-get工具手动重新下载）：')
            for i, url in download_failed_list:
                print(f'第{i}集：{url}')
    else:
        print(f"Error: get {url} failed and server return '{req.reason}'")

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="基于sole_bili_get下载合集视频")
    parser.add_argument('url', nargs='?', type=str, default='', action='store', help='合集视频链接')
    parser.add_argument('-c', '--cookie', type=str, default='', help='哔哩哔哩个人cookie隐私数据')
    parser.add_argument('-o', '--output', type=str, default='', 
                        help='下载目录, 缺省为当前目录, 会自动创建bili_tmp/和bili_output/两个子文件夹，最终的视频文件是存储于bili_output/')
    args = parser.parse_args()
    if not args.url:
        print('Error: no url!\nusage: python download_collection.py <url> [-c COOKIE] [-o OUTPUT]')
    else:
        start_time = time.time()
        output = args.output
        if (output=='') or os.path.isfile(output):
            output = Path.cwd()
        else:
            output = os.path.normpath(output)
            if not os.path.isdir(output):
                os.makedirs(output)
        print(f'output: {output}')
        sole_bili_get.utils._base_dir = output
        if args.cookie:
            cookies = sole_bili_get.utils.parse_cookies(args.cookie)
        else:
            cookies = None
        get_video_collection(args.url, cookies=cookies, output=output)
    print(f'耗时统计：{time.time()-start_time}秒')