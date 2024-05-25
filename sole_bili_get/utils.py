import os, re, requests, hashlib, pickle, platform
from contextlib import closing

__all__ = ["get_absolute_path", "find_json_dict_from_text", "Crawler", "parse_cookies"]

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
        self.chunk_size = kwargs.get('chunk_size', 1024*1024*2) #默认单次请求最大值设为2MB
        self.show_progress = kwargs.get('show_progress', True)
        self.download_info_file = get_absolute_path('./bili_tmp/crawler_download_tmp.pickle') #记录url和对应下载文件信息的临时文件路径
                                #等信息，url: (save_path, is_downloaded_flag, downloaded_bytes)
        self.error_info = ''

    def get(self):
        if (self.url is None) or (not self.url.startswith('http')):
            self.error_info = f'request url {self.url} is invalid'
            if _utils_debug: print(f'Error: {self.error_info}')
            return False
        try:
            start_byte = 0
            existed_file = self.get_local_download_info(self.url)
            if existed_file and ((self.save_path is None) or (self.save_path == existed_file[0])):
                if existed_file[1]:
                    self.save_path = existed_file[0]
                    if _utils_debug: print(f'{self.url} file is already downloaded success in {existed_file[0]}')
                    return True
                start_byte = existed_file[2]
                self.headers['Range'] = f"bytes={start_byte}-"
                if _utils_debug: print(f'the url {self.url} file({existed_file[0]}) has been downloaded before, continue to download from byte {start_byte}')
            else:
                if _utils_debug: print(f'start to download {self.url} firstly')
                if (self.save_path is not None) and os.path.exists(self.save_path):
                    if _utils_debug: print(f'remove {self.save_path} for no record in {self.download_info_file}')
                    os.remove(self.save_path)
            if _utils_debug: print(f'headers = {self.headers}, cookies = {str(self.cookies)}')
            with closing(requests.get(self.url, headers=self.headers, cookies=self.cookies, stream=True)) as response:
                #print(response.headers)
                if not response.ok:
                    if _utils_debug: print(f'Error: request get {self.url} failed for {response.reason}')
                    self.error_info = response.reason
                    return False
                suffix = minetype2suffix.get(response.headers['Content-Type'], '.unknown')
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
                total_size = float(response.headers['content-length']) + start_byte
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
                if _utils_debug: print(f'download success, saved into {self.save_path}')
                self.save_info_into_local_tmp_file(total_size, already_download=True)
                return True
        except Exception as e:
            if _utils_debug: print(f"Error(Crawler): get {self.url} failed for "
                                   f'exception([{e.__traceback__.tb_frame.f_globals["__file__"]}:'
                                   f'{e.__traceback__.tb_lineno}] {e}) occurs when analyse playinfo')
            self.error_info = e
            self.save_info_into_local_tmp_file(0)
            return False

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

if __name__ == '__main__':
    #测试断点续传功能
    url = 'https://github.com/muggledy/typora-dyzj-theme/raw/master/temp/%E9%9A%BE%E7%A0%B4%E8%88%B9.mp4'
    crawler = Crawler(url, headers={'Referer':'https://github.com/muggledy/typora-dyzj-theme/blob/master/temp/%E9%9A%BE%E7%A0%B4%E8%88%B9.mp4'})
    crawler.get()
