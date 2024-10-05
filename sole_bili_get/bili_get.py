from .utils import *
import requests, logging, \
    re, json, pickle, os, \
    subprocess, platform, sys, \
    time, argparse, colorama, \
    psutil, random, sole_bili_get
from logging.handlers import RotatingFileHandler
#from lxml import etree
from pathlib import Path
from copy import deepcopy
from . import utils
from .file_lock import LockedFile
from datetime import datetime
from itertools import count
from .av2bv import av2bv
if platform.system() == 'Windows':
    from .chrome_cookie import get_bilibili_cookie

__all__ = ['Bilibili', 'main', 'get_bilibili_cookie']

colorama.init(autoreset=True)

class Bilibili:
    def __init__(self, origin_url, **kwargs):
        if kwargs.get('base_dir') and os.path.isdir(kwargs['base_dir']):
            utils._base_dir = kwargs['base_dir']
        self.create_logger()
        self.disable_console_log = kwargs.get('disable_console_log', False) #关闭，并不是没有控制台输出，而是简单的输出一些信息，详细可以看日志
        self.origin_url = origin_url #原始请求视频链接
        self.playlists_info = {} #存放所有剧集信息
        self.fetch_playlists = kwargs.get('fetch_playlists', False) #是否自动下载全部剧集
        self.headers = kwargs.get('headers', {})
        self.cookies = kwargs.get('cookies', None)
        self.quality = kwargs.get('quality', 'MAX').upper() #下载质量选择：MAX, MIN, MANUAL
        self.force_re_download = kwargs.get('force_re_download', False)
        self.ffmpeg_debug = kwargs.get('ffmpeg_debug', False)
        self.remove_merge_materials = kwargs.get('remove_merge_materials', True) #是否删除合成材料
        self.debug_all = kwargs.get('debug_all', False)
        utils._utils_debug = self.debug_all
        self.auto_merge = kwargs.get('auto_merge', True)
        self.__crawler = Crawler(None, headers=self.headers, multi_thread_num=kwargs.get('multi_thread_num', 0),
                                 #proxies={'http':'socks5://127.0.0.1:10808','https':'socks5://127.0.0.1:10808'})
        )
        self.__download_at_once = True #每获取并解析一个剧集页面，就立即开始下载，而非等到收集完全部剧集信息后再遍历下载

    def start(self):
        if self.__bvid is None:
            self.logger.error(f'invalid request url: {self.origin_url}, can\'t start download')
            return
        if self.auto_merge:
            if not self.check_tool('ffmpeg'):
                self.__ffmpeg_exist = False
                ffmpeg_not_exist_prompt = \
                    'ffmpeg not exists, can\'t merge video and audio, you can prepare this tool and re-exec the download cmd'
            else:
                self.__ffmpeg_exist = True
        if self.force_re_download and self.fetch_playlists: #只有在指定fetch_playlists的情况下，指定force_re_download才会整个删除临时文件，全部强制重新下载，否则只是强制重新下载对应一集
            self.__force_re_download_p = float('inf')
            if os.path.exists(self.__local_playlists_info_path):
                self.logger.warning(f'delete old file {self.__local_playlists_info_path} for force_re_download')
                os.remove(self.__local_playlists_info_path)
            __local_playlists_info = {}
            self.__local_already_download_p_list = []
            self.initialize_local_download_progress_info()
        else:
            #多进程协作下载仅针对不带--force参数的情况，否则行为属于未定义，特此声明！
            if not self.initialize_local_download_progress_info():
                return
            #首先从本地获取视频信息并填充到self.playlists_info，如果视频（含子剧集）未全部下载完成，则
            #针对未下载剧集需要重新从B站服务器获取相应的剧集信息并更新本地数据
            __local_playlists_info = self.get_playlists_info_from_local()
            if self.force_re_download:
                __local_playlists_info = self.clear_download_info_for_origin_url(playlists_info=__local_playlists_info)
                if __local_playlists_info:
                    self.save_playlists_info_into_local(__local_playlists_info)
            else:
                self.__force_re_download_p = 0
            self.update_local_already_download_p_list(playlists_info=__local_playlists_info)
            if self.__local_already_download_p_list and self.__ffmpeg_exist:
                not_merged_p_list = [i for i in self.__local_already_download_p_list if \
                                     (not __local_playlists_info[i]['merge_flag'] and \
                                     ((__local_playlists_info[i].get('process') is not None) and (__local_playlists_info[i]['process'][0] == os.getpid())))]
                if not_merged_p_list:
                    self.logger.info('first, merge previously downloaded videos/audios...')
                    if self.disable_console_log:
                        print(f"Note: {', '.join(['p'+str(i) for i in not_merged_p_list])} {'are' if len(not_merged_p_list) > 1 else 'is'} "
                              f"downloaded but videos/audios not merged, merge {'them' if len(not_merged_p_list) > 1 else 'it'} firstly")
                    updated_local_playlists_info = self.check_playlists_is_merged(playlists_info=__local_playlists_info)
                    if updated_local_playlists_info is not None:
                        __local_playlists_info = updated_local_playlists_info
        self.playlists_info = deepcopy(__local_playlists_info)
        if self.get_origin_url_and_analyse() is None: #对尚未下载完成的剧集页面进行获取并得到音视频下载地址等相关信息更新到self.playlists_info中
            return
        if not self.__download_at_once:
            self.__all_downloed_flag = True #先预设能够全部下载成功，如果有一个失败了，则再置为False
            self.download_by_playlists_info()
        total, downloaded, not_download, download_failed, merged, not_merge, merge_failed = self.get_current_downloaded_info()
        self.logger.info(f"total:{total}, downloaded:{downloaded}, not_download:{not_download}, download_failed:{download_failed}, "
                         f"merged:{merged}, not_merge:{not_merge}, merge_failed:{merge_failed}")
        if self.__all_downloed_flag:
            if total == downloaded:
                all_download_ok_prompt = f'{"(all)videos locked by current bili_get process have" if total>1 else "This video has"} already been downloaded in {self.__output_dir}!'
                self.logger.info(all_download_ok_prompt)
                if self.disable_console_log:
                    print(all_download_ok_prompt)
        else:
            self.save_playlists_info_into_local()
            self.logger.info('some videos/audios download failed, you can re-exec command to download them')
            if self.disable_console_log:
                print('some videos/audios download failed, you can re-exec command to download them')
        if self.auto_merge:
            if not self.__ffmpeg_exist and downloaded != 0:
                self.logger.warning(ffmpeg_not_exist_prompt)
                if self.disable_console_log:
                    print(f'Note: {ffmpeg_not_exist_prompt}')
            else:
                self.check_playlists_is_merged()

    def update_newest_playlists_info(self, playlists_info): #上次虽然没有下载完，但可能已经下载了视频，只是音频还没有，这些信息不能被丢弃，否则会造成重复下载
        for i in playlists_info.keys():
            if self.playlists_info.get(i) is None:
                continue
            playlists_info[i]['download_flag'] = self.playlists_info[i]['download_flag']
            playlists_info[i]['merge_flag'] = self.playlists_info[i]['merge_flag']
            if self.playlists_info[i].get('video_save_path'):
                playlists_info[i]['video_save_path'] = self.playlists_info[i]['video_save_path']
            if self.playlists_info[i].get('audio_save_path'):
                playlists_info[i]['audio_save_path'] = self.playlists_info[i]['audio_save_path']
            if self.playlists_info[i].get('danmu_url'):
                playlists_info[i]['danmu_url'] = self.playlists_info[i]['danmu_url']
        self.playlists_info.update(playlists_info)

    def get_current_downloaded_info(self): #返回：(剧集总数,已下载,未下载,下载失败,已合入,未合入,合入失败)，这个统计信息比较粗略，无法区分是真的下载失败了还是正在被其他进程下载，鸡肋，也懒得改了
        if not self.playlists_info:
            return (0,0,0,0,0,0,0)
        current_info = sorted([(p_num, info['download_flag'], info['merge_flag']) for p_num, info in self.playlists_info.items()], key=lambda x:x[0])
        total = self.playlists_info[[_[0] for _ in current_info if self.playlists_info[_[0]].get('videos')][0]]['videos']
        downloaded = len([info for info in current_info if info[1] == 3])
        not_download = len([info for info in current_info if len(self.playlists_info[info[0]]) == 3]) #如果info形如
                            #{'download_flag':0, 'merge_flag':False, 'process':None}，说明还未被任何bili_get进程下载
        download_failed = total - downloaded - not_download
        if self.auto_merge and self.__ffmpeg_exist:
            merged = len([info for info in current_info if info[2]])
            not_merge = not_download
            merge_failed = total - merged - not_merge
        else:
            merged, not_merge, merge_failed = 0, total, 0
        return (total, downloaded, not_download, download_failed, merged, not_merge, merge_failed)

    @property
    def origin_url(self):
        return self.__origin_url

    @origin_url.setter
    def origin_url(self, origin_url):
        if hasattr(self, f'_{self.__class__.__name__}__origin_url') \
                and (origin_url == self.__origin_url):
            return
        avid = re.findall(r'list/([^/\?]+)', origin_url)
        if avid:
            try:
                converted_bvid = av2bv(int(avid[0]))
                _origin_url = origin_url
                origin_url = self.generate_bilibili_video_url(converted_bvid)
                prompt = f'convert origin request url from {_origin_url} to {origin_url}'
                self.logger.info(prompt)
                if self.disable_console_log:
                    print(prompt)
            except Exception as e:
                self.logger.error(f'convert {origin_url} failed for {e}')
        self.__origin_url = origin_url
        bvid = re.findall(r'video/([^/\?]+)', self.__origin_url)
        if bvid: #key id
            self.__bvid, self.__local_playlists_info_path = \
                bvid[0], get_absolute_path(f'./bili_tmp/local_playlists_info_{bvid[0]}.pickle')
            self.__output_dir = get_absolute_path(f'./bili_output/{self.__bvid}/')
        else:
            self.__bvid, self.__local_playlists_info_path = None, None
            self.__output_dir = None
        self.playlists_info = {} #origin_url重置后，所有信息都应清空，需重新执行start()
        self.__local_already_download_p_list = []
        self.__all_downloed_flag = False

    def get_origin_url_and_analyse(self):
        '''解析原始请求url并获取全部剧集的视频信息（若fetch_playlists为True且是多剧集视频的话，注意可能不全，
           即部分子剧集视频信息获取失败），返回self.playlists_info'''
        try:
            start_time = time.time()
            req = requests.get(self.origin_url, headers=self.headers, cookies=self.cookies)
            if req.ok:
                if self.debug_all:
                    local_file = get_absolute_path(f"./bili_tmp/original_url_{self.__bvid}.html")
                    Path(local_file).write_text(req.text, encoding='utf-8')
                    self.logger.info(f'get {self.origin_url} succeed and write into local file({local_file})')
                origin_video_info = self.analyse_playinfo(req.text)
                if origin_video_info is None:
                    self.logger.error(f'analyse origin {self.origin_url} html page failed')
                    if self.disable_console_log:
                        print(f'Error: analyse origin {self.origin_url} html page failed')
                    return None
                origin_video_is_downloaded_by_self = False
                if origin_video_info['p_num'] in self.playlists_info:
                    origin_video_info['process'] = self.playlists_info[origin_video_info['p_num']].get('process')
                #如果原始url视频尚未被下载，且其未被任何其他bili_get进程处理（即已处于正在下载状态的话）：则本进程下载之
                if (origin_video_info['p_num'] not in self.__local_already_download_p_list) and \
                        (self.test_playlist_is_handled_by_self(origin_video_info.get('process'), \
                            f"(get_origin_url_and_analyse)p{origin_video_info['p_num']}(test if video(origin url) is locked by self bili_get process that judge true)") or \
                        (not self.test_playlist_is_handled_by_one_process(origin_video_info.get('process'), \
                            f"(get_origin_url_and_analyse)p{origin_video_info['p_num']}(test if video(origin url) is currently downloaded by other bili_get process that judge false)"))):
                    origin_video_is_downloaded_by_self = True
                    self.logger.info(f"current bili_get process({os.getpid()}) will download origin video(p{origin_video_info['p_num']})")
                    origin_video_info['download_flag'] = 0
                    origin_video_info['merge_flag'] = False
                    origin_video_info['process'] = (os.getpid(), datetime.now().timestamp())
                    self.update_newest_playlists_info({origin_video_info['p_num']:origin_video_info})
                    self.save_playlists_info_into_local() #首个bili_get进程执行到此之前，其他bili_get进程尚无法执行，因为处于“STATE_BLOCK”状态，此行执行后，“STATE_BLOCK”状态取消，
                                                          #其他进程可以开始协作下载
                if len(self.playlists_info) != origin_video_info['videos']: #针对UP主新增剧集，本地需要新增对应的占位符供各个bili_get进程锁定下载
                    new_upload_p_list = [_ for _ in range(1, origin_video_info['videos']+1) if _ not in self.playlists_info]
                    self.logger.info(f"UP {origin_video_info['author']['name']} upload {origin_video_info['videos'] - len(self.playlists_info)} "
                                     f"new episodes({','.join(['p'+str(_) for _ in new_upload_p_list])}) for download")
                    self.save_playlists_info_into_local(dict(zip(new_upload_p_list, [None]*len(new_upload_p_list))))
                if self.debug_all:
                    self.logger.info(f'html analyse succeed: {str(origin_video_info)}')
                quality_dict = {_1:_2['quality'] for _1, _2 in origin_video_info['video_info'].items()}
                _desc = re.sub('\n',' ',origin_video_info['desc'])
                video_main_info = \
                    colored_text(f"{'(title):':>15}{origin_video_info['title']}", 'red', highlight=1) + '\n' +\
                    colored_text(f"{'(desc):':>15}{_desc}", 'red', highlight=1) + '\n' +\
                    colored_text(f"{'(author):':>15}{origin_video_info['author']['name']}", 'red', highlight=1) + '\n' +\
                    colored_text(f"{'(episodes num):':>15}{origin_video_info['videos']}", 'red', highlight=1) + '\n' +\
                    colored_text(f"{'(quality):':>15}{', '.join([_[1]+'(id:'+str(_[0])+')' for _ in quality_dict.items()])}", 'red', highlight=1)
                self.logger.info(f"origin html({origin_video_info['url']}) analyse succeed\n{video_main_info}")
                if self.disable_console_log:
                    print(colored_text(f"{'(origin url):':>15}{self.origin_url}", 'red', highlight=1) + '\n' +\
                          f"{video_main_info}")
                self.update_playlists_info_from_local() #之前如果已经锁定了一个待下载剧集，此处不会再锁定其他的，此处只是为了从本地更新最新self.playlists_info
                now_downloaded_by_other_progress_p_num = self.get_currently_downloaded_by_other_progress_playlist_p_num()
                if not ((origin_video_info['videos'] == (len(self.__local_already_download_p_list) + len(now_downloaded_by_other_progress_p_num))) and 
                        list(sorted(self.__local_already_download_p_list + now_downloaded_by_other_progress_p_num)) \
                        == list(range(1, origin_video_info['videos']+1))): #判断是否还有要下载的剧集，否则直接结束进程
                    if self.quality == 'MANUAL':
                        while 1:
                            manual_quality_id = int(input('please select quality(id): '))
                            if manual_quality_id in quality_dict.keys():
                                break
                        self.__quality_id = manual_quality_id
                    elif self.quality == 'MIN':
                        self.__quality_id = min(quality_dict.keys())
                    else: #default is MAX quality
                        self.__quality_id = max(quality_dict.keys())
                    select_down_quality_info = f'selected download quality({self.quality}):{self.__quality_id}'
                    self.logger.info(select_down_quality_info)
                    if self.disable_console_log:
                        print(select_down_quality_info)
                        if self.__local_already_download_p_list:
                            print(f"Note: {', '.join(['p'+str(_) for _ in sorted(self.__local_already_download_p_list)])} has already been downloaded in {self.__output_dir}")
                    if not ((not self.fetch_playlists) and (origin_video_info['p_num'] in \
                                (self.__local_already_download_p_list + now_downloaded_by_other_progress_p_num))): #如果仅下载原始剧集且其已被下载或正在被其他进程下载，则不需要预获取所有剧集的弹幕资源
                        self.get_danmu_urls()
                else:
                    if now_downloaded_by_other_progress_p_num:
                        self.logger.info(f'{len(self.__local_already_download_p_list)} videos has been downloaded in {self.__output_dir}, '
                                         f'{len(now_downloaded_by_other_progress_p_num)} is currently downloaded by other bili_get progress')
                    else:
                        self.logger.info(f'(all) videos has already been downloaded in {self.__output_dir}! '
                                     f'if you want to re-download, please delete {self.__local_playlists_info_path} or pass force_re_download param')
                    self.__all_downloed_flag = True
                    return self.playlists_info
                if self.__download_at_once:
                    self.__all_downloed_flag = True
                    if origin_video_is_downloaded_by_self:
                        self.download_by_playlists_info(which_p=origin_video_info['p_num'])
                if self.fetch_playlists and (origin_video_info['videos'] > 1): #遍历剧集号，只有那些被当前进程锁定的未下载剧集才会被当前进程执行下载，否则直接跳过
                    to_download_p_list = list(range(1, origin_video_info['videos']+1))
                    for iter_i in count():
                        if (len(to_download_p_list) == 0) or (iter_i > 200):
                            break
                        p = to_download_p_list.pop(0)
                        self.logger.info(f'iter to p{p} and try to lock it...')
                        if (p == origin_video_info['p_num']) or (p in self.__local_already_download_p_list):
                            self.logger.info(f'p{p} is already downloaded, iter next')
                            continue
                        self.update_playlists_info_from_local() #每次只选取并锁定一个剧集，下载完，需要重新选取并锁定另一个剧集下载
                        self.update_local_already_download_p_list()
                        if p in self.__local_already_download_p_list:
                            self.logger.info(f'p{p} is already downloaded, iter next')
                            continue
                        locked_p = sorted([_p for _p,_v in self.playlists_info.items() if ((_v.get('process') is not None) and (_v['process'][0]==os.getpid())) \
                                and ((_v.get('download_flag') is None) or ((_v.get('download_flag') is not None) and (_v['download_flag']!=3)))])
                        if not locked_p: #没有锁定的待下载剧集，说明已全部完成下载，立即结束下载流程
                            self.logger.info(f'no video is locked for current bili-get process to download, break download progress')
                            break
                        if p not in locked_p: #当前要下载的剧集号p不是当前锁定的待下载剧集号locked_p，则立即将锁定的剧集号插入到to_download_p_list队头，下载该锁定的剧集
                            to_download_p_list = locked_p[0] + [p] + to_download_p_list
                            self.logger.info(f'currently locked undownloaded p{locked_p[0]} is re-insert to_download_p_list to download')
                            continue
                        try:
                            sub_url = self.generate_bilibili_video_url(origin_video_info['bvid'], p)
                            sub_req = requests.get(sub_url, headers=self.headers, cookies=self.cookies)
                            sub_video_info = self.analyse_playinfo(sub_req.text)
                            self.logger.info(f"get and analyse sub url {sub_url} {'succeed' if sub_video_info else 'failed'}")
                            if sub_video_info is not None:
                                sub_video_info['download_flag'] = 0
                                sub_video_info['merge_flag'] = False
                                if sub_video_info['p_num'] in self.playlists_info:
                                    sub_video_info['process'] = self.playlists_info[sub_video_info['p_num']].get('process')
                                self.update_newest_playlists_info({sub_video_info['p_num']:sub_video_info})
                                if self.__download_at_once:
                                    self.download_by_playlists_info(which_p=sub_video_info['p_num'])
                                    if self.playlists_info[sub_video_info['p_num']]['download_flag'] != 3: #下载失败则重新插入to_download_p_list队头，继续尝试下载之，而非跳过
                                        to_download_p_list = [sub_video_info['p_num']] + to_download_p_list
                            else:
                                if self.disable_console_log:
                                    print(f'Error: analyse sub url {self.origin_url} html page failed')
                        except Exception as e:
                            self.logger.error(f'exception([{e.__traceback__.tb_frame.f_globals["__file__"]}:'
                                              f'{e.__traceback__.tb_lineno}] {e}) occurs when getting from {sub_url}')
                    self.update_playlists_info_from_local()
                    self.update_local_already_download_p_list() #self.__local_already_download_p_list是当前已完成下载剧集
                    not_downloaded_p_list = [_ for _ in range(1, origin_video_info['videos']+1) if _ not in self.__local_already_download_p_list] #未完成下载剧集
                    not_downloaded_and_failed_p_list = \
                        [_ for _ in not_downloaded_p_list if ((not self.test_playlist_is_handled_by_one_process(self.playlists_info[_].get('process'), \
                                                                                                                f'p{_}(for prompt show, ignored)')) or \
                        self.test_playlist_is_handled_by_self(self.playlists_info[_].get('process'), f'p{_}(for prompt show, ignored)'))] #未完成下载剧集中已下载失败的剧集
                    not_downloaded_and_is_downloading_p_list = list(set(not_downloaded_p_list) - set(not_downloaded_and_failed_p_list)) #未完成下载剧集中还正在下载的剧集
                    download_result_prompt = (f"total {origin_video_info['videos']} episodes, "
                            f"in which {len(self.__local_already_download_p_list)} {'are' if len(self.__local_already_download_p_list)>1 else 'is'} downloaded" + \
                            ((f", {','.join(['p'+str(_) for _ in not_downloaded_and_is_downloading_p_list])} {'are' if len(not_downloaded_and_is_downloading_p_list)>1 else 'is'} "
                            f"currently downloaded by other bili_get {'processes' if len(not_downloaded_and_is_downloading_p_list)>1 else 'process'}") \
                                if not_downloaded_and_is_downloading_p_list else "") + \
                            (f", {','.join(['p'+str(_) for _ in not_downloaded_and_failed_p_list])} {'are' if len(not_downloaded_p_list)>1 else 'is'} failed to download" \
                                if not_downloaded_p_list else "") + \
                            f", runtime: {time.time()-start_time:.2f}s")
                    self.logger.info(download_result_prompt)
                    if self.disable_console_log:
                        print(download_result_prompt)
                elif (origin_video_info['videos'] > 1) and (not self.fetch_playlists) \
                        and (len(self.__local_already_download_p_list) < origin_video_info['videos']):
                    print('Note: this is a multi-episode video, you can download them all at once with --playlist')
                return self.playlists_info
            else:
                self.logger.error(f"get {self.origin_url} failed and server return '{req.reason}'")
                if self.disable_console_log:
                    print(f"get {self.origin_url} failed and server return '{req.reason}'")
                return None
        except Exception as e:
            self.logger.error(f'exception([{e.__traceback__.tb_frame.f_globals["__file__"]}:'
                              f'{e.__traceback__.tb_lineno}] {e}) occurs when getting from origin {self.origin_url}')
            return None

    def analyse_playinfo(self, html_text):
        try:
            ret_info = {}
            '''html = etree.HTML(html_text, etree.HTMLParser())
            title = html.xpath('//*[@id="viewbox_report"]/div[1]/div/h1')[0].text
            ret_info['title'] = title'''
            window_playinfo = find_json_dict_from_text(html_text, 'window\.__playinfo__', 1)[0]
            window_playinfo = json.loads(window_playinfo)
            window_initial_state = find_json_dict_from_text(html_text, 'window\.__INITIAL_STATE__', 1)[0]
            window_initial_state = json.loads(window_initial_state)
            video_quality_id = window_playinfo['data']['accept_quality']
            video_quality_2_str = dict(zip(video_quality_id, window_playinfo['data']['accept_description']))
            top_video_quality_id = window_playinfo['data']['quality'] #可供下载的最大视频质量id
            video_info = {} #item: <quality_id: (quality_str, size, urls_list)>
            for v in window_playinfo['data']['dash']['video']:
                if v['id'] <= top_video_quality_id:
                    if video_info.get(v['id']) is None:
                        video_info[v['id']] = dict(zip(['quality', 'size', 'urls'], \
                                                [video_quality_2_str[v['id']], (v['width'], v['height']), []]))
                    codec_info = f"{v['codecs']}_{v['bandwidth']}_{v['frameRate']}"
                    video_info[v['id']]['urls'].append((v['baseUrl'], f'{codec_info}.base1'))
                    if v.get('base_url'):
                        video_info[v['id']]['urls'].append((v['base_url'], f'{codec_info}.base2'))
                    if v.get('backupUrl'):
                        if type(v['backupUrl']) == list:
                            video_info[v['id']]['urls'].extend([(_2, f'{codec_info}.backup1.{_1}') for _1,_2 in enumerate(v['backupUrl'],1)])
                        else:
                            video_info[v['id']]['urls'].append((v['backupUrl'], f'{codec_info}.backup1'))
                    if v.get('backup_url'):
                        if type(v['backup_url']) == list:
                            video_info[v['id']]['urls'].extend([(_2, f'{codec_info}.backup2.{_1}') for _1,_2 in enumerate(v['backup_url'],1)])
                        else:
                            video_info[v['id']]['urls'].append((v['backup_url'], f'{codec_info}.backup2'))
            ret_info['video_info'] = video_info
            ret_info['audio_url'] = []
            for v in window_playinfo['data']['dash']['audio']:
                ret_info['audio_url'].append(v['baseUrl'])
                if v.get('base_url'):
                    ret_info['audio_url'].append(v['base_url'])
                if v.get('backupUrl'):
                    if type(v['backupUrl']) == list: ret_info['audio_url'].extend(v['backupUrl'])
                    else: ret_info['audio_url'].append(v['backupUrl'])
                if v.get('backup_url'):
                    if type(v['backup_url']) == list: ret_info['audio_url'].extend(v['backup_url'])
                    else: ret_info['audio_url'].append(v['backup_url'])
            ret_info['author'] = dict(zip(['name', 'id'], \
                [window_initial_state['videoData']['owner']['name'], window_initial_state['videoData']['owner']['mid']]))
            ret_info['cover'] = window_initial_state['videoData']['pic']
            ret_info['stat'] = dict(zip(['like', 'coin', 'favorite', 'view', 'danmaku'], 
                                        [window_initial_state['videoData']['stat']['like'], 
                                        window_initial_state['videoData']['stat']['coin'], 
                                        window_initial_state['videoData']['stat']['favorite'], 
                                        window_initial_state['videoData']['stat']['view'], 
                                        window_initial_state['videoData']['stat']['danmaku']]))
            ret_info['bvid'] = window_initial_state['bvid'] #BV1vH4y137x2，https://www.bilibili.com/video/BV1vH4y137x2/
            ret_info['videos'] = window_initial_state['videoData']['videos'] #剧集总数，单集值为1
            ret_info['p_num'] = window_initial_state['p'] #当前为剧集列表中的第几集，单集值为1
            if ret_info['videos'] > 1:
                _ = [_['part'] for _ in window_initial_state['videoData']['pages'] if _['page'] == ret_info['p_num']]
                ret_info['title'] = f"p{ret_info['p_num']}_{window_initial_state['videoData']['title']}{'_'+_[0] if _ else ''}"
            else:
                ret_info['title'] = window_initial_state['videoData']['title']
            ret_info['title'] = self.normalize_filename(ret_info['title'])
            ret_info['desc'] = window_initial_state['videoData']['desc']
            ret_info['desc'] = '无' if not ret_info['desc'] else ret_info['desc']
            ret_info['url'] = self.generate_bilibili_video_url(ret_info['bvid'], 
                                                               None if (ret_info['videos'] == 1) else ret_info['p_num'])
            if self.__bvid != ret_info['bvid']:
                self.logger.warning(f"local bvid {self.__bvid} is different from analyzed {ret_info['bvid']}, "
                                 f"origin url:{self.origin_url}, current analyzed url:{ret_info['url']}")
            return ret_info
        except Exception as e:
            self.logger.error(f'exception([{e.__traceback__.tb_frame.f_globals["__file__"]}:'
                              f'{e.__traceback__.tb_lineno}] {e}) occurs when analyse playinfo')
            return None

    def download_by_playlists_info(self, which_p=None): #which_p非None：仅下载指定一集
        download_only_one = True
        download_specific_codec_video = ['avc1', 'hev1'] #同一个quality(1080P/720P)的也有多个下载链接，不同链接的视频流
        #使用的codec编解码器不同，譬如avc1.640033，hev1.1.6.L120.90，av01.0.00M.10.0.110.01.01.01.0，这个列表其实是一个优
        #先级列表，未在列表中出现的解码器优先级都极低，按照优先级下载一个成功即结束（download_only_one==True，为False会下载
        #所有解码器类型的视频，默认音视频合成的话，只会将优先级最高的那个视频和音频文件进行合成）
        def get_idx_of_specific_codedc(codec_info):
            _ = [_1 for _1,_2 in enumerate(download_specific_codec_video) if codec_info.lower().startswith(_2.lower())]
            if _ == []: return float('inf')
            else: return _[0]
        for p in sorted(self.playlists_info.keys()):
            if (which_p is not None) and (p != which_p):
                continue
            #每个剧集只能被指定的处理进程下载，bili_get进程下载前都会选取一个待下载剧集并锁定它，避免多进程重复下载同一剧集
            if (not self.force_re_download) and (not self.test_playlist_is_handled_by_self(self.playlists_info[p].get('process'), \
                    f'(download_by_playlists_info)p{p}(test if it is locked(judge true) by my self bili_get process)')):
                self.logger.error(f"can\'t download p{p} for owner handle pid({self.playlists_info[p].get('process')}) is not current bili_get progress({os.getpid()})")
                continue
            if self.playlists_info[p]['download_flag'] == 3:
                continue
            info = self.playlists_info[p]
            available_qualities = list(info['video_info'].keys())
            best_quality_idx = sorted([(i,abs(q-self.__quality_id)) 
                                       for i,q in enumerate(available_qualities)], key=lambda x:x[1])[0][0]
            best_quality = available_qualities[best_quality_idx]
            get_video_url_already_succeed = 0
            if self.danmu_urls.get(p): #弹幕文件只是附带下载，不保证下载成功
                if self.download_danmu_xml(self.danmu_urls[p], save_path=os.path.normpath(os.path.join(self.__output_dir, f"{info['title']}.xml"))):
                    danmu_ok_prompt = f"p{p} danmu xml"\
                        f" is downloaded into "+os.path.normpath(os.path.join(os.path.join(self.__output_dir, f"{info['title']}.xml")))
                    self.logger.info(danmu_ok_prompt+f" from {self.danmu_urls[p]}")
                    if self.disable_console_log: print(colored_text(danmu_ok_prompt, 'white'))
                    self.playlists_info[p]['danmu_url'] = self.danmu_urls[p]
            self.__crawler.url = self.playlists_info[p]['cover']
            self.__crawler.save_path = os.path.normpath(os.path.join(self.__output_dir, f"{info['title']}"))
            if self.__crawler.get(): #视频封面只是附带下载，不保证下载成功
                self.logger.info(f'p{p} cover is downloaded into {self.__crawler.save_path}')
                if self.disable_console_log:
                    print(colored_text(f'p{p} cover is downloaded into {self.__crawler.save_path}', 'white'))
            if self.playlists_info[p]['download_flag'] != 1:
                for url,codec_info in sorted(info['video_info'][best_quality]['urls'], 
                                             key=lambda x:get_idx_of_specific_codedc(x[1])):
                    #if not [_c for _c in download_specific_codec_video if codec_info.lower().startswith(_c.lower())]:
                    #    continue
                    downloading_video_info = "start to download "+\
                        colored_text(f"p{p}(video:{info['video_info'][best_quality]['quality']},"\
                        f"{'x'.join([str(_) for _ in info['video_info'][best_quality]['size']])},{codec_info})", 'red')+\
                        f"{' from '+info['url'] if self.disable_console_log else ''}..."
                    self.logger.info(downloading_video_info)
                    if self.disable_console_log:
                        print(downloading_video_info)
                    self.__crawler.url = url
                    self.__crawler.save_path = os.path.normpath(os.path.join(self.__output_dir, 
                        f"{info['title']}{'' if (0 == get_video_url_already_succeed) else '_'+str(get_video_url_already_succeed)}.mp4"))
                    if ((self.__force_re_download_p == float('inf')) or (self.__force_re_download_p == p)) and os.path.exists(self.__crawler.save_path):
                        self.logger.warning(f'delete old p{p} video file {self.__crawler.save_path} and re-download it')
                        os.remove(self.__crawler.save_path)
                    start_time = time.time()
                    ok = self.__crawler.get()
                    if ok:
                        get_video_url_already_succeed += 1
                        if get_video_url_already_succeed == 1:
                            self.playlists_info[p]['video_save_path'] = self.__crawler.save_path
                        self.logger.info(f"download video from {self.__crawler.url} into {self.__crawler.save_path} succeed, runtime: {time.time()-start_time:.2f}s")
                        self.playlists_info[p]['download_flag'] = 1
                        self.save_playlists_info_into_local()
                        if download_only_one: break
                    else:
                        self.logger.error(f"download video from {self.__crawler.url} failed for {self.__crawler.error_info}")
                        time.sleep(random.choice([sleep_sec * 0.1 for sleep_sec in range(10, 20)])) #惩罚
            else:
                self.logger.info(f"p{p} video has been downloaded in {self.__output_dir}")
            if self.playlists_info[p]['download_flag'] == 0:
                self.__all_downloed_flag = False
                if self.disable_console_log:
                    print(f"Error: download p{p} video failed, you can re-exec this command later")
                continue
            downloading_audio_info = "start to download " + colored_text(f"p{p}(audio)", 'blue') + "..."
            if self.disable_console_log:
                print(downloading_audio_info)
            for audio_url in info['audio_url']:
                self.logger.info(downloading_audio_info)
                self.__crawler.url = audio_url
                self.__crawler.save_path = os.path.normpath(os.path.join(self.__output_dir, f"{info['title']}_audio.mp3")) #audio may also be *.mp4 file 
                                                            #which is the same with video filename in this case, we rename it to *.mp3
                if ((self.__force_re_download_p == float('inf')) or (self.__force_re_download_p == p)) and os.path.exists(self.__crawler.save_path):
                    self.logger.warning(f'delete old p{p} audio file {self.__crawler.save_path} and re-download it')
                    os.remove(self.__crawler.save_path)
                start_time = time.time()
                ok = self.__crawler.get()
                if ok:
                    self.logger.info(f"download audio from {self.__crawler.url} into {self.__crawler.save_path} succeed, runtime: {time.time()-start_time:.2f}s")
                    if os.path.exists(self.__crawler.save_path):
                        if self.playlists_info[p].get('video_save_path') and \
                                (self.playlists_info[p]['video_save_path'] == \
                                os.path.normpath(os.path.join(self.__output_dir, f"{info['title']}{os.path.splitext(self.__crawler.save_path)[1]}"))):
                            self.playlists_info[p]['audio_save_path'] = os.path.normpath(os.path.join(self.__output_dir, f"{info['title']}.mp3"))
                        else:
                            self.playlists_info[p]['audio_save_path'] = \
                                os.path.normpath(os.path.join(self.__output_dir, f"{info['title']}{os.path.splitext(self.__crawler.save_path)[1]}"))
                        self.logger.warning(f'rename audio file {self.__crawler.save_path} => {self.playlists_info[p]["audio_save_path"]}')
                        if os.path.exists(self.playlists_info[p]['audio_save_path']):
                            os.remove(self.playlists_info[p]['audio_save_path'])
                        os.rename(self.__crawler.save_path, self.playlists_info[p]['audio_save_path'])
                    self.playlists_info[p]['download_flag'] += 2
                    self.save_playlists_info_into_local() #立即保存下载进度，避免因合成失败导致下次还要重复下载音频文件
                    if self.auto_merge and (not self.playlists_info[p]['merge_flag']) \
                            and self.merge_video_and_audio(self.playlists_info[p]['video_save_path'], self.playlists_info[p]['audio_save_path']):
                        self.playlists_info[p]['merge_flag'] = True
                    self.save_playlists_info_into_local()
                    break
                else:
                    self.logger.error(f"download audio from {self.__crawler.url} failed for {self.__crawler.error_info}")
                    time.sleep(random.choice([sleep_sec * 0.1 for sleep_sec in range(10, 20)])) #惩罚
            if self.playlists_info[p]['download_flag'] != 3:
                self.__all_downloed_flag = False
                if self.disable_console_log:
                    print(f"Error: download p{p} audio failed, you can re-exec this command later")

    def merge_video_and_audio(self, video_file, audio_file):
        if (not self.auto_merge) or (not self.__ffmpeg_exist):
            return False
        if not os.path.exists(video_file):
            self.logger.error(f'{video_file} not exist, can\'t do ffmpeg merge!')
            return False
        if not os.path.exists(audio_file):
            self.logger.error(f'{audio_file} not exist, can\'t do ffmpeg merge!')
            return False
        merge_file = '_merge'.join(os.path.splitext(video_file))
        if os.path.exists(merge_file):
            os.remove(merge_file)
        cmd = f"ffmpeg -i \"{video_file}\" -i \"{audio_file}\" -c:v copy -c:a aac -strict experimental \"{merge_file}\""
        self.logger.info(f'start merging audio and video files by exec "{cmd}"')
        if self.disable_console_log:
            print(f'start ffmpeg merging...')
        try:
            start_time = time.time()
            if self.ffmpeg_debug or self.debug_all:
                result = subprocess.run(cmd, check=True)
            else:
                result = subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            if (result.returncode == 0) and os.path.exists(merge_file):
                if self.remove_merge_materials:
                    self.logger.info(colored_text(f'success! runtime: {time.time()-start_time:.2f}s, delete merge materials, rename {merge_file} => {video_file}', 'green'))
                    os.remove(video_file)
                    os.remove(audio_file)
                    os.rename(merge_file, video_file)
                    if self.disable_console_log:
                        print(colored_text(f"ffmpeg merge success, save into {video_file}", 'green'))
                else:
                    self.logger.info(colored_text(f'success! runtime: {time.time()-start_time:.2f}s, the merged file is at {merge_file}', 'green'))
                    if self.disable_console_log:
                        print(colored_text(f"ffmpeg merge success, save into {merge_file}", 'green'))
                sys.stdout.flush()
                return True
            self.logger.error('merge failed for unknown reason!')
            if self.disable_console_log:
                print('Error: merge failed for unknown reason!')
            sys.stdout.flush()
            return False
        except Exception as e:
            self.logger.error(f'merge failed for {e}!')
            if self.disable_console_log:
                print(f'Error: merge failed for {e}!')
        sys.stdout.flush()
        return False

    def check_playlists_is_merged(self, playlists_info=None):
        if (not self.auto_merge) or (not self.__ffmpeg_exist):
            return
        self.logger.info('check if all playlists\'s video and audio are all merged...')
        flag = False
        if playlists_info is None:
            playlists_info = self.playlists_info
            flag = True
        n0 = len(playlists_info.keys()) #全部剧集总数
        n1, n2, n3, n4, n5 = 0, 0, 0, 0, 0
        for p in sorted(playlists_info.keys()):
            if playlists_info[p]['download_flag'] == 3:
                if not playlists_info[p]['merge_flag']:
                    if not self.test_playlist_is_handled_by_self(playlists_info[p].get('process'), \
                            f'(check_playlists_is_merged)p{p}(test if it is not locked(judge false) by self bili_get process)'):
                        n5 += 1 #不需要被本进程合成的数量
                        continue
                    if not self.merge_video_and_audio(playlists_info[p]['video_save_path'], playlists_info[p]['audio_save_path']):
                        n2 += 1 #此处最新合成失败的数量
                    else:
                        n4 += 1 #此处最新合成成功的数量
                        playlists_info[p]['merge_flag'] = True
                        if flag:
                            self.playlists_info = playlists_info
                            self.save_playlists_info_into_local()
                        else:
                            self.save_playlists_info_into_local(playlists_info)
                else:
                    n1 += 1 #之前已经合成的数量
            else:
                n3 += 1 #视频尚未下载成功的数量
        if flag:
            if (n1 == n0) or ((n1+n4) == n0): self.logger.info(f'all {n0} mv are merged!')
            else: self.logger.info(f'{n0-(n1+n4)} mv not merge, in which {n3} mv not downloaded. '
                                   f'for those({n0-n3}) already downloaded, {n5} mv no need to be processed by current pid({os.getpid()}), {n2} mv (ffmpeg)merge failed!')
        return (playlists_info if not flag else None) #只有在传入非None的playlists_info时，才返回更新后的它，否则返回None

    @staticmethod
    def generate_bilibili_video_url(bvid, p=None):
        if p is None:
            return f'https://www.bilibili.com/video/{bvid}'
        else:
            return f'https://www.bilibili.com/video/{bvid}/?p={p}'

    def initialize_local_download_progress_info(self): #返回True表示后续流程可以继续，否则直接退出进程
        with LockedFile(self.__local_playlists_info_path, 'r+b' if os.path.exists(self.__local_playlists_info_path) else 'w+b') as f:
            try: #初次读取没有数据会出现“io.UnsupportedOperation: read”错误，需捕捉
                data = pickle.load(f)
                if (type(data) == tuple) and (data[0] == 'STATE_BLOCK') and \
                        self.test_playlist_is_handled_by_one_process(data[1:], f'(initialize_local_download_progress_info)the playlists(test if STATE_BLOCK is valid)'):
                    #最开始若两个进程同时开始，为了避免两个进程同时去B站获取视频url
                    #下载信息并重复写入本地，只允许其中一个bili_get进程启动，另一个直接退出，这种概率很小，因为正常情况下从B站获取剧集下载信息的
                    #时间也就几秒，一般用户不会在这几秒内又启动一个bili_get进程，一般是一个进程下载了几集发现太慢等不及，才会再起一个进程并行下载
                    prompt = f'current pid {os.getpid()} can\'t start bili_get for another pid {data[1]} is getting download info from bilibili firstly'
                    self.logger.error(prompt)
                    if self.disable_console_log: print(prompt)
                    return False
                elif type(data) == dict: #playlists info
                    return True
            except:
                init_info = ('STATE_BLOCK', os.getpid(), datetime.now().timestamp())
                f.truncate(0)
                f.seek(0)
                pickle.dump(init_info, f, pickle.HIGHEST_PROTOCOL)
                f.flush()
                self.logger.info(f'pid {init_info[1]} start bili_get firstly at {timestamp2str(init_info[2])}...')
                return True
        prompt = f'pid {os.getpid()} can\'t start bili_get for unknown reason, you can delete {self.__local_playlists_info_path} and try again'
        self.logger.error(prompt)
        if self.disable_console_log: print(prompt)
        return False

    def save_playlists_info_into_local(self, playlists_info=None):
        playlists_info = self.playlists_info if playlists_info is None else playlists_info
        with LockedFile(self.__local_playlists_info_path, 'r+b') as f:
            local_playlists_info = pickle.load(f) #保存下载进度到本地时，其他bili_get进程可能已经对下载进度进行了更新，因此此处需要读取最新的下载进度
            if type(local_playlists_info) == tuple:
                select_one_to_download = False
                for i in range(1, playlists_info[list(playlists_info.keys())[0]]['videos']+1): #初次保存，入参是origin_url的剧集信息，只有这一个剧集信息，需要据此扩充全部剧集占位
                    if playlists_info.get(i) is None:
                        playlists_info[i] = {'download_flag':0, 'merge_flag':False, 'process':None} #占位，便于其他bili_get进程从该task pool选取
                    else:
                        #首次保存视频下载信息，第一个未下载视频（且必然是origin url对应剧集）被立即选取作为当前进程的下载对象
                        if playlists_info[i]['download_flag'] != 3 and self.test_playlist_is_handled_by_self(playlists_info[i].get('process'), \
                                f'(save_playlists_info_into_local)p{i}(try to select origin url to handle)'):
                            select_one_to_download = True
                        elif (playlists_info[i]['download_flag'] != 3) and (not select_one_to_download) and \
                                (not self.test_playlist_is_handled_by_one_process(playlists_info[i].get('process'), \
                                f'(save_playlists_info_into_local)p{i}(try to select origin url to handle)')):
                            self.logger.info(f'pid {os.getpid()} firstly get info of {self.__bvid}(p{i}) from bilibili and create all tasks pool')
                            select_one_to_download = True
                            playlists_info[i]['process'] = (os.getpid(), datetime.now().timestamp())
            elif type(local_playlists_info) == dict:
                all_videos_num = 0
                for p, v in playlists_info.items():
                    if v.get('videos') is not None:
                        all_videos_num = max(all_videos_num, v['videos'])
                    if p not in local_playlists_info.keys(): #UP主新增剧集占位信息保存到本地
                        local_playlists_info[p] = {'download_flag':0, 'merge_flag':False, 'process':None}
                    else:
                        if (v.get('process') is None) or (v['process'][0] != os.getpid()): #只需要更新当前进程正在处理的剧集信息到本地
                            continue
                        if self.force_re_download:
                            local_playlists_info[p] = v
                        else:
                            if (local_playlists_info[p]['download_flag'] != 3) or (not local_playlists_info[p]['merge_flag']):
                                local_playlists_info[p] = v
                all_videos_num = max(all_videos_num, len(local_playlists_info))
                if all_videos_num != len(local_playlists_info):
                    for _ in range(1, all_videos_num+1):
                        if _ not in local_playlists_info:
                            local_playlists_info[_] = {'download_flag':0, 'merge_flag':False, 'process':None}
                for p, v in local_playlists_info.items(): #如果UP主新增剧集，旧的剧集信息中的“剧集总数”字段应当更新
                    if (v.get('videos') is not None) and (v['videos'] != all_videos_num):
                        local_playlists_info[p]['videos'] = all_videos_num
                playlists_info = local_playlists_info
            f.truncate(0)
            f.seek(0)
            pickle.dump(playlists_info, f, pickle.HIGHEST_PROTOCOL)
            f.flush()
        self.logger.info(f'write playlists info into {self.__local_playlists_info_path}')

    def get_playlists_info_from_local(self, need_to_lock_merge_task=True): #从本地读取playlists_info下载进度同时锁定一个未下载剧集任务
        select_one_to_download = False
        with LockedFile(self.__local_playlists_info_path, 'r+b') as f:
            local_playlists_info = pickle.load(f)
            if type(local_playlists_info) == tuple:
                return {} #尚未从B站获取到下载信息，本地的下载进度为空
            elif type(local_playlists_info) == dict:
                for p,v in sorted(local_playlists_info.items(), key=lambda x:x[0]):
                    if ((v['download_flag'] != 3) or (not v['merge_flag'])) and \
                            (not self.test_playlist_is_handled_by_one_process(v.get('process'), \
                            f'(get_playlists_info_from_local)p{p}(clear invalid process_info that judge false)')): #清空无效的剧集process_info
                        local_playlists_info[p]['process'] = None
                    if (v['download_flag'] != 3) and self.test_playlist_is_handled_by_self(v.get('process'), \
                            f'(get_playlists_info_from_local)p{p}(select video download task that judge true)'): #已被当前进程选取
                        select_one_to_download = True
                    elif (v['download_flag'] != 3) and (not select_one_to_download) \
                            and (not self.test_playlist_is_handled_by_one_process(v.get('process'), f'(get_playlists_info_from_local)p{p}(select video download task that judge false)')):
                        local_playlists_info[p]['process'] = (os.getpid(), datetime.now().timestamp()) #选取一个未被任何其他bili_get进程处理的剧集，后续
                                                                                                       #进程也只会对process是本进程的剧集进行下载处理
                        self.logger.info(f'pid {os.getpid()} select p{p} to download')
                        select_one_to_download = True
                    if need_to_lock_merge_task:
                        if (v['download_flag'] == 3) and (not v['merge_flag']) and self.test_playlist_is_handled_by_self(v.get('process'), \
                                f'(get_playlists_info_from_local)p{p}(select ffmpeg merge task that judge rtue)'): #已被当前进程选取
                            pass
                        elif (v['download_flag'] == 3) and (not v['merge_flag']) and (not self.test_playlist_is_handled_by_one_process(v.get('process'), \
                                f'(get_playlists_info_from_local)p{p}(select ffmpeg merge task that judge false)')):
                            self.logger.info(f'pid {os.getpid()} select p{p} to merge')
                            local_playlists_info[p]['process'] = (os.getpid(), datetime.now().timestamp()) #bili_get刚执行，会找出所有已下载待合并的剧集进行合并，此处将它们全部交由一个进程处理
                f.truncate(0)
                f.seek(0)
                pickle.dump(local_playlists_info, f, pickle.HIGHEST_PROTOCOL)
                f.flush()
        self.logger.info(f'load local playlists info from {self.__local_playlists_info_path}')
        return local_playlists_info

    def get_currently_downloaded_by_other_progress_playlist_p_num(self):
        p_list = []
        for p,v in self.playlists_info.items():
            if (v['download_flag'] != 3) and self.test_playlist_is_handled_by_others(v.get('process'), \
                    f'(get_currently_downloaded_by_other_progress_playlist_p_num)p{p}(test if it is currently downloaded by other bili_get process)'):
                p_list.append(p)
        if p_list:
            self.logger.info(f"{','.join(['p'+str(i) for i in p_list])} is currently downloaded by other bili_get progress")
        return p_list

    def update_playlists_info_from_local(self): #从本地更新self.playlists_info并选取一个待下载任务
        local_playlists_info = self.get_playlists_info_from_local(need_to_lock_merge_task=False)
        for p,v in self.playlists_info.items():
            if (v.get('process') is None) or (v['process'][0] != os.getpid()):
                continue
            if (local_playlists_info[p]['download_flag'] != 3) or (not local_playlists_info[p]['merge_flag']):
                local_playlists_info[p] = v
        self.playlists_info = local_playlists_info
        return self.playlists_info

    def test_playlist_is_handled_by_self(self, process_info, desc=None): #根据剧集信息判断其是否正在被当前bili_get进程处理
        if not process_info:
            return False
        if process_info[0] != os.getpid():
            return False
        if self.test_playlist_is_handled_by_one_process(process_info, desc=desc):
            return True
        return False

    def test_playlist_is_handled_by_others(self, process_info, desc=None): #根据剧集信息判断其是否正在被其他bili_get进程处理
        if not process_info:
            return False
        if (process_info[0] != os.getpid()) and self.test_playlist_is_handled_by_one_process(process_info, desc=desc):
            return True
        return False

    def test_playlist_is_handled_by_one_process(self, process_info, desc=None): #判断剧集是否正在被其记录的进程所处理，如果没有被任何有效进程处理则返回False
        if not process_info:
            return False
        try:
            pid, timestamp = process_info
            process = psutil.Process(pid)
            judge, reason = True, 'null'
            if process.create_time() > timestamp:
                judge, reason = False, 'pid create time is latter than playlist record process time'
            elif 'python' not in process.name().lower():
                judge, reason = False, 'this is not a python process'
            elif passed_time_exceeds_specified_hours(timestamp, 1): #如果某个进程下载一个视频一个小时还未完成，说明该进程存在错误卡住或
                            #根本不是bili_get下载进程（只是碰巧该进程号存在且过了前面两个if判断而已），则当前bili_get进程也会尝试下载它
                judge, reason = False, 'process time too long that exceeds one hour, may not be bili_get program or process stuck'
            self.logger.info(f'{desc if desc else "the playlist"} is processed by pid {pid}, timestamp is {timestamp2str(timestamp)}. '
                f'get pid info: name({process.name()}), status({process.status()}), create_time({timestamp2str(process.create_time())}), '
                f'parent_pid({process.ppid()}), memory_info({process.memory_info()}). judge: {judge}' + (f', reason: {reason}' if not judge else ''))
            return judge
        except psutil.NoSuchProcess:
            return False

    def update_local_already_download_p_list(self, playlists_info=None):
        if playlists_info is None:
            playlists_info = self.playlists_info
        self.__local_already_download_p_list = \
            [(v['p_num'] if v.get('p_num') else k) for k,v in playlists_info.items() if v['download_flag'] == 3]

    def get_danmu_urls(self):
        api = 'https://api.bilibili.com/x/web-interface/view?bvid=' + self.__bvid
        try:
            response = requests.get(api, headers=self.headers)
            response.raise_for_status()
            danmu_url = lambda cid: "https://comment.bilibili.com/"+str(cid)+".xml"
            self.danmu_urls = {page['page']:danmu_url(page['cid']) for page in response.json()['data']['pages']}
            self.logger.info(f'get danmu urls success for {len(self.danmu_urls)} episodes({self.danmu_urls})')
            if self.disable_console_log:
                print(f'get danmu urls success for {len(self.danmu_urls)} episodes')
        except Exception as e:
            self.logger.error(f"get video info from api {api} failed for {e}, thus can't download danmu")
            self.danmu_urls = {}
        return self.danmu_urls

    def download_danmu_xml(self, url, save_path):
        try:
            response = requests.get(url, headers=self.headers)
            response.encoding = 'utf-8'
            Path(save_path).write_text(response.text, encoding='utf-8')
            return True
        except Exception as e:
            self.logger.error(f"get danmu xml file from {url} failed for {e}")
        return False

    @property
    def headers(self):
        return self.__headers
    
    @headers.setter
    def headers(self, headers):
        if not hasattr(self, f'_{self.__class__.__name__}__headers'):
            self.__headers = {'User-Agent':
'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36', 
'Referer':'https://www.bilibili.com/'}
        self.__headers.update(headers)

    @staticmethod
    def normalize_filename(filename): #Windows文件名不能含有\/:*?"<>|
        illegal_chars = r'\/:*?"<>|'
        filename = ''.join(char for char in filename if char not in illegal_chars)
        return filename

    def clear_download_info_for_origin_url(self, playlists_info=None):
        p = re.findall(r'video/[^/\?]+/\?p=(\d+)', self.origin_url)
        p = int(p[0]) if p else 1
        self.__force_re_download_p = p
        if (not self.playlists_info) and (playlists_info is None):
            return None
        flag = True if playlists_info is None else False
        playlists_info = self.playlists_info if playlists_info is None else playlists_info
        if p in playlists_info.keys():
            playlists_info[p]['download_flag'] = 0
            playlists_info[p]['merge_flag'] = False
            playlists_info[p]['video_save_path'] = ''
            playlists_info[p]['audio_save_path'] = ''
            playlists_info[p]['danmu_url'] = ''
            self.logger.info(f'delete p{p} download info of original url {self.origin_url} for force_re_download')
        if flag:
            self.playlists_info = playlists_info
            return self.playlists_info
        return playlists_info

    def clear_crawler_thread_pool_resource(self):
        if self.__crawler is None:
            return
        self.__crawler.clear_thread_pool_resource()

    @property
    def disable_console_log(self):
        return self.__disable_console_log

    @disable_console_log.setter
    def disable_console_log(self, disable_console_log):
        set_flag = hasattr(self, f'_{self.__class__.__name__}__disable_console_log')
        if (self.logger is not None) and (self.logger_console_handler is not None):
            if ((not set_flag) and disable_console_log):
                self.logger.removeHandler(self.logger_console_handler)
            elif (set_flag and self.__disable_console_log and (not disable_console_log)):
                if not self.logger_concole_handler_add_once:
                    Bilibili.logger_concole_handler_add_once = True
                    self.logger.addHandler(self.logger_console_handler)
            elif (set_flag and (not self.__disable_console_log) and disable_console_log):
                self.logger.removeHandler(self.logger_console_handler)
        self.__disable_console_log = disable_console_log

    logger = None
    logger_console_handler = None
    logger_concole_handler_add_once = False

    def create_logger(self):
        if self.logger is not None:
            return
        Bilibili.logger = logging.getLogger(self.__class__.__name__)
        self.logger.setLevel(logging.DEBUG) #logger.setLevel()对低于该等级的日志丢弃，否则再转发给FileHandler和StreamHandler处理，因此该等级必须最低
        Bilibili.logger_console_handler = logging.StreamHandler()
        self.logger_console_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s(%(funcName)s:%(lineno)s): %(message)s'))
        if not (hasattr(self, f'_{self.__class__.__name__}__disable_console_log') and self.disable_console_log):
            if not self.logger_concole_handler_add_once:
                Bilibili.logger_concole_handler_add_once = True
                self.logger.addHandler(self.logger_console_handler)
        file_log_handler = RotatingFileHandler(filename=get_absolute_path(f'./bili_tmp/download.{os.getpid()}.{datetime.now().timestamp()}.log'), 
                                               maxBytes=1024*1024, backupCount=3, encoding='utf-8') #logging.FileHandler(filename='log', encoding='utf-8')
        file_log_handler.setFormatter(logging.Formatter('%(asctime)s[%(name)s] - %(pathname)s[line:%(lineno)d(%(funcName)s)] - %(levelname)s: %(message)s'))
        file_log_handler.setLevel(logging.INFO)
        self.logger.addHandler(file_log_handler)

    @staticmethod
    def check_tool(tool_name):
        try:
            if platform.system() == 'Windows':
                subprocess.run(['where', tool_name], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            else:
                subprocess.run(['which', tool_name], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            return True
        except subprocess.CalledProcessError:
            return False

def main():
    parser = argparse.ArgumentParser(description="A simple tool to download videos from bilibili{*≧∀≦}")
    parser.add_argument('url', nargs='?', type=str, default='', action='store', help='Bilibili video url(BV format)')
    parser.add_argument('-q', '--quality', type=str, default='MAX', choices=['MAX', 'MIN', 'MANUAL'], help='Select the video quality, default is `MAX`')
    parser.add_argument('-c', '--cookie', type=str, default='', help='Your bilibili website cookie. Support to get cookie from chrome automatically by `-c chrome` on windows')
    parser.add_argument('-o', '--output', type=str, default='', 
                        help='Videos and temp file\'s output directory, default is current working path, will create ./bili_tmp/ and ./bili_output/')
    parser.add_argument('--debug', action="store_true", help='Open all debug on console')
    parser.add_argument('--playlist', action="store_true", help='Download video playlists')
    parser.add_argument('--force', action="store_true", help='Force to re-download videos')
    parser.add_argument('-t', '--threads', type=int, default=0, help='Auxiliary download threads num, total number is (threads+1), you can set `-t 0` to disable multithreading')
    parser.add_argument('--nomerge', action="store_true", help='Don\'t auto merge videos and audios')
    parser.add_argument('-v', '--version', action="store_true", help='Show the version of bili-get')
    
    args = parser.parse_args()
    if args.version:
        print(sole_bili_get.__version__)
        return
    url = args.url
    if not url:
        print('usage: bili-get [-h] [-q {MAX,MIN,MANUAL}] [-c COOKIE] [-o OUTPUT] [--debug] [--playlist] [--force] [-t THREADS] [--nomerge] [-v] url\n'
              'bili-get: error: the following arguments are required: url')
        return
    output = args.output
    if (output=='') or os.path.isfile(output):
        output = Path.cwd()
    else:
        output = os.path.normpath(output)
        if not os.path.isdir(output):
            os.makedirs(output)
    utils._base_dir = output #for chrome_cookie.py
    if args.debug:
        utils._utils_debug = True #for chrome_cookie.py
    if args.cookie:
        if (platform.system() == 'Windows') and (args.cookie.lower().strip() == 'chrome'):
            bili_ck = get_bilibili_cookie()
            if bili_ck is not None:
                args.cookie = bili_ck
            else:
                print('(ignore)get bilibili cookie from local for chrome failed')
        cookies = parse_cookies(args.cookie)
    else:
        cookies = None
    if args.debug:
        print(f"input params: url({url}), quality({args.quality}), cookie({str(cookies)}), "
              f"output({output}), total_download_threads({args.threads}), download_playlist({args.playlist}), force_download({args.force}), not_merge({args.nomerge})")
    else:
        print(f'output: {output}')
    bilibili = Bilibili(url, disable_console_log=False if args.debug else True, 
        fetch_playlists=args.playlist, quality=args.quality, force_re_download=args.force, base_dir=output, 
        auto_merge=True if not args.nomerge else False, ffmpeg_debug=True if args.debug else False, 
        remove_merge_materials=True, debug_all=args.debug, headers={}, cookies=cookies, multi_thread_num=args.threads)
    bilibili.start()
    bilibili.clear_crawler_thread_pool_resource()

if __name__ == '__main__':
    '''bilibili = Bilibili('https://www.bilibili.com/video/BV1z84y1r7Tc', disable_console_log=True, 
                        fetch_playlists=True, quality = 'MAX', force_re_download=False, base_dir='C:\\Users\\muggledy\\Downloads\\', auto_merge=True, ffmpeg_debug=False, 
                        remove_merge_materials=True, debug_all=False, headers={})
    bilibili.start()'''
    pass