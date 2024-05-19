from .utils import *
import requests, logging, \
    re, json, pickle, os, \
    subprocess, platform, sys, \
    time, argparse
from logging.handlers import RotatingFileHandler
#from lxml import etree
from pathlib import Path
from copy import deepcopy
from . import utils

__all__ = ['Bilibili', 'main']

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
        self.quality = kwargs.get('quality', 'MAX').upper() #下载质量选择：MAX, MIN, MANUAL
        self.force_re_download = kwargs.get('force_re_download', False)
        self.ffmpeg_debug = kwargs.get('ffmpeg_debug', False)
        self.remove_merge_materials = kwargs.get('remove_merge_materials', True) #是否删除合成材料
        self.debug_all = kwargs.get('debug_all', False)
        utils._utils_debug = self.debug_all
        self.auto_merge = kwargs.get('auto_merge', True)
        self.__crawler = Crawler(None, headers=self.headers)
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
        if self.force_re_download:
            if os.path.exists(self.__local_playlists_info_path):
                self.logger.warning(f'delete old file {self.__local_playlists_info_path} for force_re_download')
                os.remove(self.__local_playlists_info_path)
            __local_playlists_info = {}
            self.__local_already_download_p_list = []
        else:
            #首先从本地获取视频信息并填充到self.playlists_info，如果视频（含子剧集）未全部下载完成，则
            #针对未下载剧集需要重新从B站服务器获取相应的剧集信息并更新本地数据
            __local_playlists_info = self.get_playlists_info_from_local()
            self.__local_already_download_p_list = \
                [v['p_num'] for k,v in __local_playlists_info.items() if v['download_flag'] == 3]
            if self.__local_already_download_p_list and self.__ffmpeg_exist:
                not_merged_p_list = [i for i in self.__local_already_download_p_list if not __local_playlists_info[i]['merge_flag']]
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
        if not self.__all_downloed_flag:
            self.save_playlists_info_into_local()
            if not self.__download_at_once:
                self.__all_downloed_flag = True #先预设能够全部下载成功，如果有一个失败了，则再置为False
        else:
            if self.auto_merge:
                if not self.__ffmpeg_exist:
                    self.logger.warning(ffmpeg_not_exist_prompt)
                    if self.disable_console_log: print(f'Note: {ffmpeg_not_exist_prompt}')
                else: self.check_playlists_is_merged()
            return
        self.download_by_playlists_info()
        if self.__all_downloed_flag:
            self.logger.info(f'(all) videos has already been downloaded in {self.__output_dir}!')
        else:
            self.logger.info('some videos/audios download failed, you can re-exec command to download them')
        if self.auto_merge:
            if not self.__ffmpeg_exist:
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
        self.playlists_info.update(playlists_info)

    @property
    def origin_url(self):
        return self.__origin_url

    @origin_url.setter
    def origin_url(self, origin_url):
        if hasattr(self, f'_{self.__class__.__name__}__origin_url') \
                and (origin_url == self.__origin_url):
            return
        self.__origin_url = origin_url
        bvid = re.findall(r'video/([^/?]+)', self.__origin_url)
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
            new_add_info_num = 0
            start_time = time.time()
            req = requests.get(self.origin_url, headers=self.headers)
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
                if origin_video_info['p_num'] not in self.__local_already_download_p_list:
                    origin_video_info['download_flag'] = 0
                    origin_video_info['merge_flag'] = False
                    self.update_newest_playlists_info({origin_video_info['p_num']:origin_video_info})
                    new_add_info_num += 1
                if self.debug_all:
                    self.logger.info(f'html analyse succeed: {str(origin_video_info)}')
                quality_dict = {_1:_2['quality'] for _1, _2 in origin_video_info['video_info'].items()}
                _desc = re.sub('\n',' ',origin_video_info['desc'])
                video_main_info = f"{'(title):':>15}"\
                    f"{origin_video_info['title']}\n{'(desc):':>15}{_desc}\n"\
                    f"{'(episodes num):':>15}{origin_video_info['videos']}"\
                    f"\n{'(quality):':>15}{', '.join([_[1]+'(id:'+str(_[0])+')' for _ in quality_dict.items()])}"
                self.logger.info(f"origin html({origin_video_info['url']}) analyse succeed\n{video_main_info}")
                if self.disable_console_log:
                    print(f"{'(origin url):':>15}{self.origin_url}\n{video_main_info}")
                if not ((origin_video_info['videos'] == len(self.__local_already_download_p_list)) and 
                        list(sorted(self.__local_already_download_p_list)) == list(range(1, origin_video_info['videos']+1))):
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
                            print(f"Note: {', '.join(['p'+str(_) for _ in self.__local_already_download_p_list])} has already been downloaded in {self.__output_dir}")
                    if not ((not self.fetch_playlists) and (origin_video_info['p_num'] in self.__local_already_download_p_list)):
                        self.get_danmu_urls()
                else:
                    self.logger.info(f'(all) videos has already been downloaded in {self.__output_dir}! '
                                     f'if you want to re-download, please delete {self.__local_playlists_info_path} or pass force_re_download param')
                    self.__all_downloed_flag = True
                    return self.playlists_info
                if self.__download_at_once:
                    self.__all_downloed_flag = True
                    self.download_by_playlists_info(which_p=origin_video_info['p_num'])
                if self.fetch_playlists and (origin_video_info['videos'] > 1):
                    for p in range(1, origin_video_info['videos']+1):
                        if (p == origin_video_info['p_num']) or (p in self.__local_already_download_p_list):
                            continue
                        try:
                            sub_url = self.generate_bilibili_video_url(origin_video_info['bvid'], p)
                            sub_req = requests.get(sub_url, headers=self.headers)
                            sub_video_info = self.analyse_playinfo(sub_req.text)
                            self.logger.info(f"get and analyse sub url {sub_url} {'succeed' if sub_video_info else 'failed'}")
                            if sub_video_info is not None:
                                sub_video_info['download_flag'] = 0
                                sub_video_info['merge_flag'] = False
                                self.update_newest_playlists_info({sub_video_info['p_num']:sub_video_info})
                                new_add_info_num += 1
                                if self.__download_at_once:
                                    self.download_by_playlists_info(which_p=sub_video_info['p_num'])
                            else:
                                if self.disable_console_log:
                                    print(f'Error: analyse sub url {self.origin_url} html page failed')
                        except Exception as e:
                            self.logger.error(f'exception([{e.__traceback__.tb_frame.f_globals["__file__"]}:'
                                              f'{e.__traceback__.tb_lineno}] {e}) occurs when getting from {sub_url}')
                    if new_add_info_num + len(self.__local_already_download_p_list) == origin_video_info['videos']:
                        self.logger.info(f"all playlists html analyse succeed(p1~p{origin_video_info['videos']})" + 
                            (f", in which {','.join(['p'+str(i) for i in self.__local_already_download_p_list])} info "
                             f"(already downloaded) get from local)! runtime: {time.time()-start_time:.2f}s" 
                            if self.__local_already_download_p_list else f', runtime: {time.time()-start_time:.2f}s'))
                    else:
                        self.logger.warning(f"{origin_video_info['videos'] - (new_add_info_num + len(self.__local_already_download_p_list))} "
                                         "sub videos info fetch failed!")
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
                    video_info[v['id']]['urls'].append((v['baseUrl'], codec_info))
            ret_info['video_info'] = video_info
            ret_info['audio_url'] = window_playinfo['data']['dash']['audio'][0]['baseUrl']
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
            if self.playlists_info[p]['download_flag'] == 3:
                continue
            info = self.playlists_info[p]
            available_qualities = list(info['video_info'].keys())
            best_quality_idx = sorted([(i,abs(q-self.__quality_id)) 
                                       for i,q in enumerate(available_qualities)], key=lambda x:x[1])[0][0]
            best_quality = available_qualities[best_quality_idx]
            get_video_url_already_succeed = 0
            if self.danmu_urls.get(p):
                if self.download_danmu_xml(self.danmu_urls[p], save_path=os.path.join(self.__output_dir, f"{info['title']}.xml")):
                    danmu_ok_prompt = f"p{p} danmu xml file is downloaded into "+os.path.join(self.__output_dir, f"{info['title']}.xml")
                    self.logger.info(danmu_ok_prompt+f" from {self.danmu_urls[p]}")
                    if self.disable_console_log: print(danmu_ok_prompt)
                    self.playlists_info[p]['danmu_url'] = self.danmu_urls[p]
            if self.playlists_info[p]['download_flag'] != 1:
                for url,codec_info in sorted(info['video_info'][best_quality]['urls'], 
                                             key=lambda x:get_idx_of_specific_codedc(x[1])):
                    #if not [_c for _c in download_specific_codec_video if codec_info.lower().startswith(_c.lower())]:
                    #    continue
                    downloading_video_info = f"start to download p{p}(video:{info['video_info'][best_quality]['quality']},"\
                        f"{'x'.join([str(_) for _ in info['video_info'][best_quality]['size']])},{codec_info})"\
                        f"{' from '+info['url'] if self.disable_console_log else ''}..."
                    self.logger.info(downloading_video_info)
                    if self.disable_console_log:
                        print(downloading_video_info)
                    self.__crawler.url = url
                    self.__crawler.save_path = os.path.join(self.__output_dir, 
                        f"{info['title']}{'' if (0 == get_video_url_already_succeed) else '_'+str(get_video_url_already_succeed)}.mp4")
                    if self.force_re_download and os.path.exists(self.__crawler.save_path):
                        self.logger.warning(f'delete old p{p} video file {self.__crawler.save_path} for force_re_download')
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
                        self.__all_downloed_flag = False
                        self.logger.error(f"download video from {self.__crawler.url} failed for {self.__crawler.error_info}")
                        if self.disable_console_log:
                            print(f"Error: download p{p} video failed, you can re-exec this command later")
            else:
                self.logger.info(f"p{p} video has been downloaded in {self.__output_dir}")
            if self.playlists_info[p]['download_flag'] == 0:
                continue
            self.logger.info(f"start to download p{p}(audio)...")
            if self.disable_console_log:
                print(f"start to download p{p}(audio)...")
            self.__crawler.url = info['audio_url']
            self.__crawler.save_path = os.path.join(self.__output_dir, f"{info['title']}_audio.mp3") #audio may also be *.mp4 file which is the same with video filename
                                                                                            #in this case, we rename it to *.mp3
            if self.force_re_download and os.path.exists(self.__crawler.save_path):
                self.logger.warning(f'delete old p{p} audio file {self.__crawler.save_path} for force_re_download')
                os.remove(self.__crawler.save_path)
            start_time = time.time()
            ok = self.__crawler.get()
            if ok:
                self.logger.info(f"download audio from {self.__crawler.url} into {self.__crawler.save_path} succeed, runtime: {time.time()-start_time:.2f}s")
                if os.path.exists(self.__crawler.save_path):
                    if self.playlists_info[p].get('video_save_path') and \
                        (self.playlists_info[p]['video_save_path'] == os.path.join(self.__output_dir, f"{info['title']}{os.path.splitext(self.__crawler.save_path)[1]}")):
                        self.playlists_info[p]['audio_save_path'] = os.path.join(self.__output_dir, f"{info['title']}.mp3")
                    else:
                        self.playlists_info[p]['audio_save_path'] = os.path.join(self.__output_dir, f"{info['title']}{os.path.splitext(self.__crawler.save_path)[1]}")
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
            else:
                self.__all_downloed_flag = False
                self.logger.error(f"download audio from {self.__crawler.url} failed for {self.__crawler.error_info}")
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
        try:
            start_time = time.time()
            if self.ffmpeg_debug or self.debug_all:
                result = subprocess.run(cmd, check=True)
            else:
                result = subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            if (result.returncode == 0) and os.path.exists(merge_file):
                if self.remove_merge_materials:
                    self.logger.info(f'success! runtime: {time.time()-start_time:.2f}s, delete merge materials, rename {merge_file} => {video_file}')
                    os.remove(video_file)
                    os.remove(audio_file)
                    os.rename(merge_file, video_file)
                    if self.disable_console_log:
                        print(f"ffmpeg merge success, save into {video_file}")
                else:
                    self.logger.info(f'success! runtime: {time.time()-start_time:.2f}s, the merged file is at {merge_file}')
                    if self.disable_console_log:
                        print(f"ffmpeg merge success, save into {merge_file}")
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
        n1, n2, n3, n4 = 0, 0, 0, 0
        for p in sorted(playlists_info.keys()):
            if playlists_info[p]['download_flag'] == 3:
                if not playlists_info[p]['merge_flag']:
                    if not self.merge_video_and_audio(playlists_info[p]['video_save_path'], playlists_info[p]['audio_save_path']):
                        n2 += 1 #此处最新合成失败的数量
                    else:
                        n4 += 1 #此处最新合成成功的数量
                        playlists_info[p]['merge_flag'] = True
                        if flag:
                            self.playlists_info = playlists_info
                        self.save_playlists_info_into_local()
                else:
                    n1 += 1 #之前已经合成的数量
            else:
                n3 += 1 #视频尚未下载成功的数量
        if flag:
            if (n1 == n0) or ((n1+n4) == n0): self.logger.info(f'all {n0} mv are merged!')
            else: self.logger.info(f'{n0-(n1+n4)} mv not merge, in which {n3} mv not downloaded, {n2} mv (ffmpeg)merge failed!')
        return (playlists_info if not flag else None) #只有在传入非None的playlists_info时，才返回更新后的它，否则返回None

    @staticmethod
    def generate_bilibili_video_url(bvid, p=None):
        if p is None:
            return f'https://www.bilibili.com/video/{bvid}'
        else:
            return f'https://www.bilibili.com/video/{bvid}/?p={p}'

    def save_playlists_info_into_local(self):
        with open(self.__local_playlists_info_path, 'wb') as f:
            pickle.dump(self.playlists_info, f, pickle.HIGHEST_PROTOCOL)
        self.logger.info(f'write playlists info into {self.__local_playlists_info_path}')

    def get_playlists_info_from_local(self):
        if not os.path.exists(self.__local_playlists_info_path):
            self.logger.info(f'{self.__local_playlists_info_path} not exists')
            return {}
        with open(self.__local_playlists_info_path, 'rb') as f:
            local_playlists_info = pickle.load(f)
        self.logger.info(f'load local playlists info from {self.__local_playlists_info_path}')
        return local_playlists_info

    def get_danmu_urls(self):
        api = 'https://api.bilibili.com/x/web-interface/view?bvid=' + self.__bvid
        try:
            json = requests.get(api, headers=self.headers).json()
            danmu_url = lambda cid: "https://comment.bilibili.com/"+str(cid)+".xml"
            self.danmu_urls = {page['page']:danmu_url(page['cid']) for page in json['data']['pages']}
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
        file_log_handler = RotatingFileHandler(filename=get_absolute_path(f'./bili_tmp/log'), 
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
    parser.add_argument('url', help='bilibili video url')
    parser.add_argument('-q', '--quality', type=str, default='MAX', choices=['MAX', 'MIN', 'MANUAL'], help='select the video quality')
    parser.add_argument('-c', '--cookie', type=str, default='', help='your bilibili website cookie')
    parser.add_argument('-o', '--output', type=str, default='', help='videos and temp file\'s output directory, default is current working path')
    parser.add_argument('--debug', action="store_true", help='open all debug')
    parser.add_argument('--playlist', action="store_true", help='download video playlists')
    parser.add_argument('--force', action="store_true", help='force to re-download videos')
    parser.add_argument('--nomerge', action="store_true", help='don\'t auto merge videos and audios')
    
    args = parser.parse_args()
    url = args.url
    output = args.output
    if (output=='') or os.path.isfile(output):
        output = Path.cwd()
    else:
        output = os.path.normpath(output)
        if not os.path.isdir(output):
            os.makedirs(output)
    if args.debug:
        print(f"params: url({url}), quality({args.quality}), cookie({args.cookie if args.cookie else 'None'}), "
              f"output({output}), download_playlist({args.playlist}), force_download({args.force}), not_merge({args.nomerge})")
    else:
        print(f'output: {output}')
    bilibili = Bilibili(url, disable_console_log=False if args.debug else True, 
        fetch_playlists=args.playlist, quality=args.quality, force_re_download=args.force, base_dir=output, 
        auto_merge=True if not args.nomerge else False, ffmpeg_debug=True if args.debug else False, 
        remove_merge_materials=True, debug_all=args.debug, headers={'Cookie':args.cookie} if args.cookie!='' else {})
    bilibili.start()

if __name__ == '__main__':
    '''bilibili = Bilibili('https://www.bilibili.com/video/BV1z84y1r7Tc', disable_console_log=True, 
                        fetch_playlists=True, quality = 'MAX', force_re_download=False, base_dir='C:\\Users\\muggledy\\Downloads\\', auto_merge=True, ffmpeg_debug=False, 
                        remove_merge_materials=True, debug_all=False, headers={})
    bilibili.start()'''
    pass