
from utils import *
import requests, logging, \
    re, json, pickle, os, \
    subprocess, platform, sys, time
#from lxml import etree
from pathlib import Path
import utils

__all__ = ['Bilibili']

class Bilibili:
    def __init__(self, origin_url, **kwargs):
        if kwargs.get('base_dir') and os.path.isdir(kwargs['base_dir']):
            utils._base_dir = kwargs['base_dir']
        self.create_logger()
        self.disable_console_log = kwargs.get('disable_console_log', False)
        self.origin_url = origin_url #原始请求视频链接
        self.playlists_info = {} #存放所有剧集信息
        self.fetch_playlists = kwargs.get('fetch_playlists', False) #是否自动下载全部剧集
        self.headers = kwargs.get('headers', {})
        self.quality = kwargs.get('quality', 'MAX').upper() #下载质量选择：MAX, MIN, MANUAL
        self.force_re_download = kwargs.get('force_re_download', False)
        self.ffmpeg_debug = kwargs.get('ffmpeg_debug', False)
        self.remove_merge_materials = kwargs.get('remove_merge_materials', True) #是否删除合成材料
        self.__crawler = Crawler(None)

    def start(self):
        if self.__bvid is None:
            self.logger.error(f'invalid request url: {self.origin_url}, can\'t start download')
            return
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
            local_playlists_info = {}
            self.__local_already_download_p_list = []
        else:
            #首先从本地获取视频信息，如果视频（含子剧集）未全部下载完成，则
            #针对未下载剧集需要重新从B站服务器获取相应的剧集信息并更新本地数据
            local_playlists_info = self.get_playlists_info_from_local()
            self.__local_already_download_p_list = \
                [v['p_num'] for k,v in local_playlists_info.items() if v['download_flag'] == 3]
        if self.get_origin_url_and_analyse() is None:
            return
        for i in self.playlists_info.keys():
            if local_playlists_info.get(i) is None:
                continue
            self.playlists_info[i]['download_flag'] = local_playlists_info[i]['download_flag']
        local_playlists_info.update(self.playlists_info)
        self.playlists_info = local_playlists_info #;print(self.playlists_info)
        if not self.__all_downloed_flag:
            self.save_playlists_info_into_local()
        else:
            if not self.__ffmpeg_exist: self.logger.warning(ffmpeg_not_exist_prompt)
            else: self.check_playlists_is_merged()
            return
        self.download_by_playlists_info()
        if self.__all_downloed_flag:
            self.logger.info(f'(all) videos has already been downloaded in {self.__output_dir}!')
        else:
            self.logger.info('some videos/audios download failed, you can re-exec command to download them')
        if not self.__ffmpeg_exist:
            self.logger.warning(ffmpeg_not_exist_prompt)
        else:
            self.check_playlists_is_merged()

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
            self.playlists_info = {}
            start_time = time.time()
            req = requests.get(self.origin_url, headers=self.headers)
            if req.ok:
                if False: #only for debug
                    local_file = get_absolute_path(f"./bili_tmp/original_url_{self.__bvid}.html")
                    Path(local_file).write_text(req.text, encoding='utf-8')
                    self.logger.info(f'get {self.origin_url} succeed and write into local file({local_file})')
                origin_video_info = self.analyse_playinfo(req.text)
                if origin_video_info is None:
                    self.logger.error(f'analyse origin {self.origin_url} html page failed')
                    return None
                if origin_video_info['p_num'] not in self.__local_already_download_p_list:
                    origin_video_info['download_flag'] = 0
                    origin_video_info['merge_flag'] = 0
                    self.playlists_info[origin_video_info['p_num']] = origin_video_info
                #self.logger.info(f'html analyse secceed: {str(origin_video_info)}')
                quality_dict = {_1:_2['quality'] for _1, _2 in origin_video_info['video_info'].items()}
                _desc = re.sub('\n',' ',origin_video_info['desc'])
                self.logger.info(f"origin html({origin_video_info['url']}) analyse succeed\n{'(title):':>15}"
                    f"{origin_video_info['title']}\n{'(desc):':>15}{_desc}\n"
                    f"{'(episodes num):':>15}{origin_video_info['videos']}"
                    f"\n{'(quality):':>15}{', '.join([_[1]+'(id:'+str(_[0])+')' for _ in quality_dict.items()])}")
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
                    self.logger.info(f'selected download quality({self.quality}):{self.__quality_id}')
                else:
                    self.logger.info(f'(all) videos has already been downloaded in {self.__output_dir}! '
                                     f'if you want to re-download, please delete {self.__local_playlists_info_path} or pass force_re_download param')
                    self.__all_downloed_flag = True
                if self.fetch_playlists and (origin_video_info['videos'] > 1):
                    for p in range(1, origin_video_info['videos']+1):
                        if (p == origin_video_info['p_num']) or (p in self.__local_already_download_p_list):
                            continue
                        try:
                            sub_url = self.generate_bilibili_video_url(origin_video_info['bvid'], p)
                            sub_req = requests.get(sub_url, headers=self.headers)
                            sub_video_info = self.analyse_playinfo(sub_req.text)
                            if sub_video_info is not None:
                                sub_video_info['download_flag'] = 0
                                sub_video_info['merge_flag'] = 0
                                self.playlists_info[sub_video_info['p_num']] = sub_video_info
                            self.logger.info(f"get and analyse sub url {sub_url} {'succeed' if sub_video_info else 'failed'}")
                        except Exception as e:
                            self.logger.error(f'exception([{e.__traceback__.tb_frame.f_globals["__file__"]}:'
                                              f'{e.__traceback__.tb_lineno}] {e}) occurs when getting from {sub_url}')
                    if len(self.playlists_info) + len(self.__local_already_download_p_list) == origin_video_info['videos']:
                        self.logger.info(f"all playlists html analyse succeed(p1~p{origin_video_info['videos']})" + 
                            (f", in which {','.join(['p'+str(i) for i in self.__local_already_download_p_list])} info "
                             f"already(downloaded) get from local)! runtime: {time.time()-start_time:.2f}s" 
                            if self.__local_already_download_p_list else f', runtime: {time.time()-start_time:.2f}s'))
                    else:
                        self.logger.warning(f"{origin_video_info['videos'] - (len(self.playlists_info) + len(self.__local_already_download_p_list))} "
                                         "sub videos info fetch failed!")
                return self.playlists_info
            else:
                self.logger.error(f"get {self.origin_url} failed and server return '{req.reason}'")
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
            ret_info['desc'] = window_initial_state['videoData']['desc']
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

    def download_by_playlists_info(self):
        failed_flag = False
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
            if self.playlists_info[p]['download_flag'] == 3:
                continue
            info = self.playlists_info[p]
            available_qualities = list(info['video_info'].keys())
            best_quality_idx = sorted([(i,abs(q-self.__quality_id)) 
                                       for i,q in enumerate(available_qualities)], key=lambda x:x[1])[0][0]
            best_quality = available_qualities[best_quality_idx]
            get_video_url_already_succeed = 0
            if self.playlists_info[p]['download_flag'] != 1:
                for url,codec_info in sorted(info['video_info'][best_quality]['urls'], 
                                             key=lambda x:get_idx_of_specific_codedc(x[1])):
                    #if not [_c for _c in download_specific_codec_video if codec_info.lower().startswith(_c.lower())]:
                    #    continue
                    self.logger.info(f"start to download p{p}(video:{info['video_info'][best_quality]['quality']},"
                                     f"{'x'.join([str(_) for _ in info['video_info'][best_quality]['size']])},{codec_info})...")
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
                        self.logger.info(f"download video from {self.__crawler.url} into {self.__crawler.save_path} succeed, runtime: {time.time()-start_time:.2f}s")
                        self.playlists_info[p]['download_flag'] = 1
                        self.save_playlists_info_into_local()
                        if download_only_one: break
                    else:
                        failed_flag = True
                        self.logger.error(f"download video from {self.__crawler.url} failed for {self.__crawler.error_info}")
            else:
                self.logger.info(f"p{p} video has been downloaded in {self.__output_dir}")
            if self.playlists_info[p]['download_flag'] == 0:
                continue
            self.logger.info(f"start to download p{p}(audio)...")
            self.__crawler.url = info['audio_url']
            self.__crawler.save_path = os.path.join(self.__output_dir, f"{info['title']}.mp3")
            if self.force_re_download and os.path.exists(self.__crawler.save_path):
                self.logger.warning(f'delete old p{p} audio file {self.__crawler.save_path} for force_re_download')
                os.remove(self.__crawler.save_path)
            start_time = time.time()
            ok = self.__crawler.get()
            if ok:
                self.logger.info(f"download audio from {self.__crawler.url} into {self.__crawler.save_path} succeed, runtime: {time.time()-start_time:.2f}s")
                self.playlists_info[p]['download_flag'] += 2
                if (not self.playlists_info[p]['merge_flag']) \
                        and self.merge_video_and_audio(os.path.splitext(self.__crawler.save_path)[0]):
                    self.playlists_info[p]['merge_flag'] = True
                self.save_playlists_info_into_local()
            else:
                failed_flag = True
                self.logger.error(f"download audio from {self.__crawler.url} failed for {self.__crawler.error_info}")
        if not failed_flag:
            self.__all_downloed_flag = True

    def merge_video_and_audio(self, filename):
        if not self.__ffmpeg_exist:
            return False
        if (not os.path.exists(f'{filename}.mp4')) or (not os.path.exists(f'{filename}.mp3')):
            self.logger.error(f'{filename}.mp4 or mp3 not exist, can\'t do merge!')
            return False
        cmd = f"ffmpeg -i {filename}.mp4 -i {filename}.mp3 -c:v copy -c:a aac -strict experimental {filename}_merge.mp4"
        self.logger.info(f'start merging audio and video files by exec "{cmd}"')
        try:
            start_time = time.time()
            if self.ffmpeg_debug:
                result = subprocess.run(cmd, check=True)
            else:
                result = subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            if (result.returncode == 0) and os.path.exists(f'{filename}_merge.mp4'):
                if self.remove_merge_materials:
                    self.logger.info(f'success! runtime: {time.time()-start_time:.2f}s, delete merge materials, rename {filename}_merge.mp4 => {filename}.mp4')
                    os.remove(f'{filename}.mp4')
                    os.remove(f'{filename}.mp3')
                    os.rename(f'{filename}_merge.mp4', f'{filename}.mp4')
                else:
                    self.logger.info(f'success! runtime: {time.time()-start_time:.2f}s, the merged file is at {filename}_merge.mp4')
                sys.stdout.flush()
                return True
            self.logger.error('merge failed for unknown reason!')
            sys.stdout.flush()
            return False
        except Exception as e:
            self.logger.error(f'merge failed for {e}!')
        sys.stdout.flush()
        return False

    def check_playlists_is_merged(self):
        if not self.__ffmpeg_exist:
            return
        self.logger.info('check if all playlists\'s video and audio are all merged...')
        n0 = len(self.playlists_info.keys()) #全部剧集总数
        n1, n2, n3, n4 = 0, 0, 0, 0
        for p in sorted(self.playlists_info.keys()):
            if self.playlists_info[p]['download_flag'] == 3:
                if not self.playlists_info[p]['merge_flag']:
                    if not self.merge_video_and_audio(os.path.join(self.__output_dir, self.playlists_info[p]['title'])):
                        n2 += 1 #此处最新合成失败的数量
                    else:
                        n4 += 1 #此处最新合成成功的数量
                        self.playlists_info[p]['merge_flag'] = True
                        self.save_playlists_info_into_local()
                else:
                    n1 += 1 #之前已经合成的数量
            else:
                n3 += 1 #视频尚未下载成功的数量
        if (n1 == n0) or ((n1+n4) == n0): self.logger.info(f'all {n0} mv are merged!')
        else: self.logger.info(f'{n0-(n1+n4)} mv not merge, in which {n3} mv not downloaded, {n2} mv (ffmpeg)merge failed!')

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

    @property
    def disable_console_log(self):
        return self.__disable_console_log

    @disable_console_log.setter
    def disable_console_log(self, disable_console_log):
        set_flag = hasattr(self, f'_{self.__class__.__name__}__disable_console_log')
        if hasattr(self, f'_{self.__class__.__name__}__console_log_handler'):
            if ((not set_flag) and disable_console_log): pass
            elif ((not set_flag) and (not disable_console_log)) or \
                    (set_flag and self.__disable_console_log and (not disable_console_log)):
                self.logger.addHandler(self.__console_log_handler)
            elif (set_flag and (not self.__disable_console_log) and disable_console_log):
                self.logger.removeHandler(self.__console_log_handler)
        self.__disable_console_log = disable_console_log

    def create_logger(self):
        self.logger = logging.getLogger(self.__class__.__name__)
        self.logger.setLevel(logging.DEBUG) #logger.setLevel()对低于该等级的日志丢弃，否则再转发给FileHandler和StreamHandler处理，因此该等级必须最低
        self.__console_log_handler = logging.StreamHandler()
        self.__console_log_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s(%(funcName)s:%(lineno)s): %(message)s'))
        if hasattr(self, f'_{self.__class__.__name__}__disable_console_log') and (not self.disable_console_log):
            self.logger.addHandler(self.__console_log_handler)
        file_log_handler = logging.FileHandler(filename='log', encoding='utf-8')
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

if __name__ == '__main__':
    bilibili = Bilibili('https://www.bilibili.com/video/BV1gm411U7HJ/', disable_console_log=False, 
                        fetch_playlists=False, quality = 'MAX', force_re_download=False, base_dir='D:\\workspace\\ttt\\', ffmpeg_debug=False, 
                        remove_merge_materials=True, headers=
                        {'Cookie':"SL_GWPT_Show_Hide_tmp=1; SL_wptGlobTipTmp=1; SL_G_WPT_TO=en; SESSDATA=7357eb0a%2C1726132706%2Cdb56e%2A31CjDZrOmSdkiHTj61Lgicy4QxIpklarykOm8fNzwlQAeqXJMTjnqe8vE836hiAd_jueESVk1ObGN3RVRKR2pDSUZQeFhrbktoMFhZY2Z5REdRV25vbC1jZ3RGOFMyazI1UGpjTUZ3ZUs3SzNYQi1aR2RvUzhtRDZ0SFZvcHVEWDRhZEQ0ZDRyenpBIIEC; buvid3=7D9A3E89-DD2A-18EB-7C6A-EE67ED1DEACA15388infoc; b_nut=1714788015; CURRENT_FNVAL=4048; share_source_origin=WEIXIN; _uuid=761047D26-D2F3-845A-526F-E4E4D4107C771015546infoc; bili_ticket=eyJhbGciOiJIUzI1NiIsImtpZCI6InMwMyIsInR5cCI6IkpXVCJ9.eyJleHAiOjE3MTUwNDcyMTYsImlhdCI6MTcxNDc4Nzk1NiwicGx0IjotMX0.to_MI_pLJYy4SMPB-L_Hku6AHQxPCDTVSs3GPx1SWW0; bili_ticket_expires=1715047156; buvid4=4633C0F9-A85E-E7E8-E194-6E2A18F95B6116740-024050402-YSL4Y8j9yPQ4xf%2FwHi58Dg%3D%3D; buvid_fp=fbda979bc28293fc0d4e3ec0c241726d; rpdid=|(umkY)mY~mm0J'u~uR~))|u); sid=6kvjoki3; bsource=search_google; CURRENT_QUALITY=80; b_lsid=EB764D10B_18F42A3AE16; enable_web_push=DISABLE; header_theme_version=CLOSE; bmg_af_switch=1; bmg_src_def_domain=i1.hdslb.com; home_feed_column=5; browser_resolution=1920-919"})
    bilibili.start()