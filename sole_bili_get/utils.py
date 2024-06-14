import os, re, requests, hashlib, pickle, platform, \
    threading, time, random
from contextlib import closing
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy

__all__ = ["get_absolute_path", "find_json_dict_from_text", "Crawler", 
           "parse_cookies", "colored_text", "timestamp2str", "is_time_in_oneday", 
           "passed_time_exceeds_specified_hours"]

_utils_debug = False
_base_dir = os.path.dirname(__file__)

def get_absolute_path(relative_path):
    absolute_path = \
        os.path.normpath(os.path.join(\
        _base_dir, relative_path))
    absolute_path += \
        ('' if os.path.split(relative_path)[1] else 
        ('\\' if platform.system() == 'Windows' else '/'))
    parent_dir = os.path.dirname(absolute_path) #os.path.dirname('c:\\xxx\\yyy\\') returns "c:\\xxx\\yyy"
    if not os.path.exists(parent_dir):
        if _utils_debug: print(f'create directory: {parent_dir}')
        os.makedirs(parent_dir)
    return absolute_path

def find_json_dict_from_text(text, start_str=None, num=float('inf')):
    stack = []
    start, end = 0, 0
    json_dict = []
    if start_str != None:
        re_text = re.findall(start_str + r'[\s\S]*', text)
        text = re_text[0] if re_text else text
    for i, c in enumerate(text):
        #print(stack, text[i:i+100])
        if c == '{':
            if stack == []:
                start = i
            stack.append(c)
        elif c == '}':
            if stack and stack[-1] == '{':
                stack.pop()
            if stack == []:
                end = i
                json_dict.append(text[start:end+1])
                if len(json_dict) >= num:
                    break
    return json_dict

def divide_interval(start, end, n, float_flag=True):
    if n <= 0: n = 1
    step = (end - start) / n
    ret = [start + i * step for i in range(n + 1)]
    if ret[-1] != end:
        ret[-1] = end
    if not float_flag:
        ret = [int(_) for _ in ret]
    return ret

def md5(str):
    md5gen = hashlib.md5()
    md5gen.update(str.encode())
    md5code = md5gen.hexdigest()
    return md5code

minetype2suffix = {'video/mp4':'mp4','video/x-flv':'flv','audio/mpeg':'mp3',
                   'audio/mpeg':'mpga','image/png':'png','image/jpeg':'jpg',
                   'image/bmp':'bmp','image/x-icon':'ico','application/vnd.android.package-archive':'apk',
                   'image/gif':'gif','application/zip':'zip','application/x-tar':'tar',
                   'audio/x-mpegurl':'m3u','audio/mp4a-latm':'m4a','image/jpeg':'jpeg',
                   'application/x-gzip':'gz'}

class ProgressBar:
    def __init__(self, title, count, total):
        self.info = "%.2f%%|%s| %s【%s】 %.2fMB/%.2fMB"
        self.title = title
        self.total = total
        self.count = count
        self.state = "正在下载"
    
    def __get_info(self):
        now=self.count/1048576
        end=self.total/1048576
        _info = self.info % (100*now/end, '█'*(int(20*(now/end)))+' '*(int(20*((end-now)/end))), \
            self.state, self.title, now, end)
        return _info
    
    def refresh(self, count):
        self.count += count
        end_str = "\r"
        if self.count >= self.total:
            end_str = '\n'
            self.state="下载完成"
        print(self.__get_info(), end=end_str)

class Crawler: #当前只能用于下载二进制文件，待完善改进
    def __init__(self, url, **kwargs):
        self.url = url
        self.headers = kwargs.get('headers', {})
        self.cookies = kwargs.get('cookies', None)
        self.save_path = kwargs.get('save_path', None)
        self.chunk_size = kwargs.get('chunk_size', 1024*1024*1) #默认单次请求最大值设为1MB
        self.show_progress = kwargs.get('show_progress', True)
        self.proxies = kwargs.get('proxies', None)
        self.error_info = ''
        self.timeout = (10, 30)
        self.download_info_file = get_absolute_path('./bili_tmp/crawler_download_tmp.pickle') #记录url和对应下载文件信息的临时文件路径
                                #等信息，url: (save_path, is_downloaded_flag, downloaded_bytes)
        #下面参数用于支持多线程下载
        self.workers = None
        self.multi_thread_num = kwargs.get('multi_thread_num', 0) #多线程下载，线程数：multi_thread_num+1
        self.save_file_obj = None
        self.save_file_lock = threading.Lock()
        self.progress = None

    def get(self):
        if (self.url is None) or (not self.url.startswith('http')):
            self.error_info = f'request url {self.url} is invalid'
            if _utils_debug: print(f'Error: {self.error_info}')
            return False
        try:
            start_byte = 0
            continue_download_flag = False
            existed_file = self.get_local_download_info(self.url)
            if existed_file and ((self.save_path is None) or (self.save_path == existed_file[0])):
                if existed_file[1]:
                    if _utils_debug: print(f'{self.url} file is already downloaded success in {existed_file[0]}')
                    return True
                self.save_path = existed_file[0]
                start_byte = existed_file[2]
                continue_download_flag = True
                if _utils_debug: print(f'the url {self.url} file({existed_file[0]}) has been downloaded before, continue to download from byte {start_byte}')
            else:
                if _utils_debug: print(f'start to download {self.url} firstly')
                if (self.save_path is not None) and os.path.exists(self.save_path):
                    if _utils_debug: print(f'remove {self.save_path} for no record in {self.download_info_file}')
                    os.remove(self.save_path)
            if self.headers.get('Range'):
                del self.headers['Range']
            start_time = time.time()
            response = requests.get(self.url, headers=self.headers, cookies=self.cookies, stream=True, timeout=self.timeout, proxies=self.proxies)
            if not response.ok:
                if _utils_debug: print(f'Error: request get {self.url}(to get total size) failed for {response.reason}')
                self.error_info = response.reason
                return False
            end_byte = int(float(response.headers['content-length']))-1 #i.e., end_byte+1 == total_size
            total_size = end_byte+1
            if not continue_download_flag:
                self.reset_save_path_by_response_content_type(response.headers['Content-Type'])
            if (end_byte - start_byte > (self.chunk_size*4)) and (self.multi_thread_num > 0) and \
                    ((end_byte - start_byte)/(self.multi_thread_num+1) > (self.chunk_size*4)): #只有在每个线程平均要下载的数据量大于self.chunk_size*4时才会真的启用多线程下载
                if _utils_debug: print(f'headers = {self.headers}, cookies = {str(self.cookies)}, range = ({(start_byte, end_byte)})')
                if self.show_progress:
                    self.progress = ProgressBar(f"{self.multi_thread_num+1}-threads:{response.headers['Content-Type']}", 0, total=total_size)
                    self.progress.refresh(count=start_byte)
                self.save_file_obj = open(self.save_path, 'wb')
                multi_thread_download_ret = self.download_with_threadpool(start_byte, end_byte)
                if multi_thread_download_ret:
                    if _utils_debug: print(f'download success, saved into {self.save_path}, consume time:{time.time()-start_time:.2f}s')
                    self.save_info_into_local_tmp_file(total_size, already_download=True) #多线程方式不支持中断续传，只有下载成功才会本地记录
                self.save_file_obj.close()
                self.save_file_obj = None
                self.progress = None
                return multi_thread_download_ret
            self.headers['Range'] = f"bytes={start_byte}-{end_byte}"
            if _utils_debug: print(f'headers = {self.headers}, cookies = {str(self.cookies)}')
            with closing(requests.get(self.url, headers=self.headers, cookies=self.cookies, stream=True, timeout=self.timeout, proxies=self.proxies)) as response:
                #print(response.headers)
                if not response.ok:
                    if _utils_debug: print(f'Error: request get {self.url} failed for {response.reason}')
                    self.error_info = response.reason
                    return False
                if self.show_progress:
                    progress = ProgressBar(response.headers['Content-Type'], 0, total=total_size)
                    progress.refresh(count=start_byte)
                iter_num = 0
                with open(self.save_path, 'ab') as save_f:
                    for data in response.iter_content(chunk_size=self.chunk_size):
                        if self.show_progress:
                            progress.refresh(count=len(data))
                        save_f.write(data)
                        save_f.flush()
                        iter_num += 1
                        self.save_info_into_local_tmp_file(start_byte+iter_num*self.chunk_size)
                if _utils_debug: print(f'download success, saved into {self.save_path}, consume time:{time.time()-start_time:.2f}s')
                self.save_info_into_local_tmp_file(total_size, already_download=True)
                return True
        except Exception as e:
            if self.save_file_obj is not None:
                self.save_file_obj.close()
                self.save_file_obj = None
            if self.progress is not None:
                self.progress = None
            if _utils_debug: print(f"Error(Crawler): get {self.url} failed for "
                                   f'exception([{e.__traceback__.tb_frame.f_globals["__file__"]}:'
                                   f'{e.__traceback__.tb_lineno}] {e}) occurs when analyse playinfo')
            self.error_info = e
            self.save_info_into_local_tmp_file(0)
            return False

    def reset_save_path_by_response_content_type(self, content_type):
        suffix = minetype2suffix.get(content_type, '.unknown')
        if self.save_path is None:
            self.save_path = self.gen_default_save_path(suffix)
            if _utils_debug: print(f'generate default save_path: {self.save_path}')
        elif (suffix != '.unknown') and (not self.save_path.endswith(suffix)):
            old_path = self.save_path
            split_save_path = os.path.splitext(self.save_path)
            if (split_save_path[-1] != '') and re.findall(r'[\u4e00-\u9fa5]+', split_save_path[-1]): #避免“哈哈.图片”这种中文名称中含“.”的被错误切割为('哈哈', '.图片')
                split_save_path = (self.save_path, '')
            if split_save_path[-1] != '':
                self.save_path = split_save_path[0] + '.' + suffix
            else:
                self.save_path += f'.{suffix}'
            self.save_path = os.path.normpath(self.save_path)
            if _utils_debug: print(f'change save_path from {old_path} to {self.save_path}')

    def download_one_block(self, start_byte, end_byte):
        headers = deepcopy(self.headers)
        headers['Range'] = f"bytes={start_byte}-{end_byte}"
        time.sleep(random.choice([sleep_sec * 0.1 for sleep_sec in range(5, 10)])) #惩罚
        try:
            with closing(requests.get(self.url, headers=headers, cookies=self.cookies, stream=True, timeout=self.timeout, proxies=self.proxies)) as response:
                if not response.ok:
                    if _utils_debug: print(f'Error: thread-{threading.get_ident()} request get {self.url} failed for {response.reason}')
                    self.error_info = response.reason
                    return False
                pos = start_byte
                for data in response.iter_content(chunk_size=self.chunk_size):
                    self.save_file_lock.acquire()
                    self.save_file_obj.seek(pos)
                    self.save_file_obj.write(data)
                    if self.show_progress and (self.progress is not None):
                        self.progress.refresh(count=len(data))
                    self.save_file_lock.release()
                    pos += self.chunk_size
            if _utils_debug: print(f'thread-{threading.get_ident()} download bytes({start_byte}:{end_byte}) success')
            return True
        except Exception as e:
            if _utils_debug: print(f'Error: thread-{threading.get_ident()} download bytes({start_byte}:{end_byte}) failed for {e}')
            return False

    def download_with_threadpool(self, start_byte, end_byte):
        if (self.multi_thread_num <= 0) or (not self.workers):
            if _utils_debug: print(f'Error: multi_thread_num is {self.multi_thread_num}, workers is {self.workers}, cannot download with threadpool')
            return
        threads_num = self.multi_thread_num + 1
        intervals = divide_interval(start_byte, end_byte, threads_num, float_flag=False)
        intervals = list(zip(intervals, intervals[1:]))
        intervals = [intervals[0]] + [(_[0]+1,_[1]) for _ in intervals[1:]]
        if _utils_debug: print(f'(download_with_threadpool) Crawler({self}) split {start_byte}:{end_byte}(bytes) into {intervals}')
        #workers = ThreadPoolExecutor(max_workers=threads_num)
        future_download = {self.workers.submit(self.download_one_block, start_byte=intervals[i][0], end_byte=intervals[i][1]):\
                       intervals[i] for i in range(threads_num)}
        failed_list = []
        for task in as_completed(future_download):
            if not task.result():
                failed_list.append(future_download[task])
        if failed_list: #存在分块下载失败，再次尝试
            future_download = {self.workers.submit(self.download_one_block, start_byte=i[0], end_byte=i[1]):\
                       i for i in failed_list}
            failed_list = []
            for task in as_completed(future_download):
                if not task.result():
                    failed_list.append(future_download[task])
        #workers.shutdown(wait=True)
        if failed_list:
            return False #二次下载失败
        return True

    def clear_thread_pool_resource(self):
        self.multi_thread_num = 0

    @property
    def multi_thread_num(self):
        return self.__multi_thread_num

    @multi_thread_num.setter
    def multi_thread_num(self, multi_thread_num):
        num_chg = False
        if hasattr(self, f'_{self.__class__.__name__}__multi_thread_num'):
            if self.__multi_thread_num != multi_thread_num:
                self.__multi_thread_num = multi_thread_num
                num_chg = True
        else:
            self.__multi_thread_num = multi_thread_num
            num_chg = True
        if num_chg and (self.__multi_thread_num > 0):
            if self.workers is not None:
                if _utils_debug: print(f'Crawler({self}) shutdown threadpool')
                self.workers.shutdown(wait=True)
                self.workers = None
            if self.__multi_thread_num > 0:
                if _utils_debug: print(f'Crawler({self}) create a threadpool with {self.multi_thread_num + 1} threads')
                self.workers = ThreadPoolExecutor(max_workers=self.multi_thread_num + 1)
        if (multi_thread_num <= 0) and (self.workers is not None):
            if _utils_debug: print(f'Crawler({self}) shutdown threadpool')
            self.workers.shutdown(wait=True)
            self.workers = None

    @property
    def url(self):
        return self.__url

    @url.setter
    def url(self, url):
        if hasattr(self, f'_{self.__class__.__name__}__url'):
            if url == self.__url: return
            else:
                self.save_path = None
                self.error_info = ''
                #print('Info: request url changed, please reset save_path')
        self.__url = url

    @property
    def headers(self):
        return self.__headers

    @headers.setter
    def headers(self, headers):
        if not hasattr(self, f'_{self.__class__.__name__}__headers'):
            self.__headers = {'User-Agent':
'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'}
        self.__headers.update(headers)

    def gen_default_save_path(self, suffix):
        rel_path = './bili_output/' +  md5(self.url)\
            + [_ for _ in self.url.split('/') if _ != ''][-1]
        if not suffix.startswith('.'):
            suffix = '.' + suffix
        _suffix = [_suffix for _suffix in 
            [(f'.{_}' if not _.startswith('.') else _) for _ in minetype2suffix.values()] if rel_path.endswith(_suffix)]
        if _suffix:
            suffix = _suffix[0]
        if not rel_path.endswith(suffix):
            rel_path += suffix
        return get_absolute_path(rel_path)

    def get_local_download_info(self, url=None):
        if not os.path.exists(self.download_info_file):
            return None
        with open(self.download_info_file, 'rb') as f:
            data = pickle.load(f)
        if url is not None:
            return data.get(url, None)
        return data

    def save_info_into_local_tmp_file(self, downloaded_bytes, already_download=False):
        if (self.save_path is None) or (not os.path.exists(self.save_path)):
            return
        data = {}
        if os.path.exists(self.download_info_file):
            with open(self.download_info_file, 'rb') as f:
                data = pickle.load(f)
        data.update({self.url : (self.save_path, already_download, downloaded_bytes)})
        with open(self.download_info_file, 'wb') as f:
            pickle.dump(data, f, pickle.HIGHEST_PROTOCOL)

def parse_cookies(cookies_str):
    cookies_dict = {}
    for cookie in cookies_str.split('; '):
        if '=' in cookie:
            key, value = cookie.split('=', 1)
            cookies_dict[key] = value
    return cookies_dict

fore_color = {
    'black': 30, 'red':31, 'green':32, 'yellow':33, 'blue':34, 'purplered':35, 'cyan':36, 'white':37
}
back_color = {
    'black': 40, 'red':41, 'green':42, 'yellow':43, 'blue':44, 'purplered':45, 'cyan':46, 'white':47
}

def colored_text(text, fore='green', back='black', highlight=0):
    fore = str(fore_color.get(fore.lower(), fore_color['white']))
    back = str(back_color.get(back.lower(), back_color['black']))
    if highlight not in [0, 1, 4, 5, 7, 8]:
        highlight = 0
    highlight = str(highlight)
    return '\033[' + highlight + ';' + fore + ';' + back + 'm' + text + '\033[0m'

def timestamp2str(timestamp):
    dt_object = datetime.fromtimestamp(timestamp)
    dt_string = dt_object.strftime('%Y-%m-%d %H:%M:%S.%f')
    return dt_string

def is_time_in_oneday(timestamp, interval, strict_check_day=True): #interval in [1,24]
    if interval not in range(1, 25):
        print(f'Warn(is_time_in_oneday): change param interval from {interval} to 24')
        interval = 24
    t1 = datetime.fromtimestamp(timestamp)
    t2 = datetime.now()
    if strict_check_day:
        return (t1.date() == t2.date() and 
            abs(t2 - t1) <= timedelta(hours=interval))
    else:
        return abs(t2 - t1) <= timedelta(hours=interval)

def passed_time_exceeds_specified_hours(timestamp, interval):
    t1 = datetime.fromtimestamp(timestamp)
    t2 = datetime.now()
    return abs(t2 - t1) > timedelta(hours=interval)

if __name__ == '__main__':
    #测试断点续传功能（multi_thread_num=0时）以及是否启用多线程下载的时间消耗
    _utils_debug = True
    url = 'https://github.com/muggledy/typora-dyzj-theme/raw/master/temp/%E9%9A%BE%E7%A0%B4%E8%88%B9.mp4'
    start_time = time.time()
    crawler = Crawler(url, headers={'Referer':'https://github.com/muggledy/typora-dyzj-theme/blob/master/temp/%E9%9A%BE%E7%A0%B4%E8%88%B9.mp4'}, multi_thread_num=5, \
                      proxies={'http':'socks5://127.0.0.1:10808','https':'socks5://127.0.0.1:10808'})
    crawler.get()
    crawler.clear_thread_pool_resource()
    print(f'consume time:{time.time()-start_time:.2f}s')