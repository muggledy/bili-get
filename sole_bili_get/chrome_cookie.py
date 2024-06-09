import os
import json
import base64
import sqlite3
import shutil
import json
from datetime import datetime, timedelta
import win32crypt  # pip install pypiwin32
from Crypto.Cipher import AES  # pip install pycryptodome
from .utils import get_absolute_path, is_time_in_oneday
from . import utils

'''
Copy from: https://thepythoncode.com/article/extract-chrome-cookies-python
https://stackoverflow.com/questions/76440733/unable-to-open-cookie-file
https://www.jianshu.com/p/d72e9aa51e4d'''

__all__ = ['get_cookies', 'get_bilibili_cookie']

def get_chrome_datetime(chromedate):
    """Return a `datetime.datetime` object from a chrome format datetime
    Since `chromedate` is formatted as the number of microseconds since January, 1601"""
    if chromedate != 86400000000 and chromedate:
        try:
            return (datetime(1601, 1, 1) + timedelta(microseconds=chromedate)).strftime("%Y-%m-%d %H:%M:%S")
        except Exception as e:
            if utils._utils_debug: print(f"Error: {e}, chromedate: {chromedate}")
            return chromedate
    else:
        return ""

def get_encryption_key():
    local_state_path = os.path.join(os.environ["USERPROFILE"],
                                    "AppData", "Local", "Google", "Chrome",
                                    "User Data", "Local State")
    with open(local_state_path, "r", encoding="utf-8") as f:
        local_state = f.read()
        local_state = json.loads(local_state)

    # decode the encryption key from Base64
    key = base64.b64decode(local_state["os_crypt"]["encrypted_key"])
    # remove 'DPAPI' str
    key = key[5:]
    # return decrypted key that was originally encrypted
    # using a session key derived from current user's logon credentials
    # doc: http://timgolden.me.uk/pywin32-docs/win32crypt.html
    return win32crypt.CryptUnprotectData(key, None, None, None, 0)[1]

def decrypt_data(data, key):
    try:
        # get the initialization vector
        iv = data[3:15]
        data = data[15:]
        # generate cipher
        cipher = AES.new(key, AES.MODE_GCM, iv)
        # decrypt password
        return cipher.decrypt(data)[:-16].decode()
    except:
        try:
            return str(win32crypt.CryptUnprotectData(data, None, None, None, 0)[1])
        except:
            # not supported
            return ""

def get_domain_info(select=None, domain=None):
    domain_name = '1'
    domain_query = '0'
    if select is None:
        domain_query = input(
            "\nIn which domain do you want to search?\n1) All domains\n2) Manual domain\n").strip()
    if ((select is not None) and (select=='1')) or (domain_query[0] == '1'):
        return domain_name
    elif ((select is not None) and (select=='2')) or (domain_query[0] == '2'):
        if domain is None:
            domain_name = input("Type the domain(e.g: google.com): ").strip()
        else:
            domain_name = domain.strip()
        return domain_name
    else:
        return domain_name

def get_db_path_info(select=None):
    db_path_select_method = '0'
    if select is None:
        db_path_select_method = input(
            "Choose database path:\n1) Automatic\n2) Manual\n").strip()
    if ((select is not None) and (select=='1')) or (db_path_select_method == '1'):
        db_path = [os.path.join(os.environ["USERPROFILE"], "AppData", "Local",
                               "Google", "Chrome", "User Data", "Default", "Network", "Cookies"),
                   os.path.join(os.environ["USERPROFILE"], "AppData", "Local",
                               "Google", "Chrome", "User Data", "Default", "Cookies"),] #此处添加chrome cookies所有可能的存储路径
    elif ((select is not None) and (select=='2')) or (db_path_select_method == '2'):
        db_path = [input("Type the full directory of your database(including db file).\n").strip(),]
    for path in db_path:
        if os.path.exists(path):
            if utils._utils_debug: print(f"Found database path({path})")
            return path
    if utils._utils_debug: print(f"Database path not found({db_path})")
    return None

def get_cookies(db_select=None, domain_select=None, domain=None):
    cookies_data = []
    # copy the file to current directory
    # as the database will be locked if chrome is currently open
    filename = "chrome_cookies.db"
    db_filepath = get_absolute_path(os.path.join('./bili_tmp', filename))
    ck_filepath = get_absolute_path(os.path.join('./bili_tmp', f'{filename}.txt'))

    need_to_del_ck_file_flag = False
    local_data = None
    if os.path.exists(ck_filepath):
        with open(ck_filepath, 'r', encoding='utf-8') as f:
            try:
                local_data = eval(f.read())
                old_time = local_data.pop()
                if not is_time_in_oneday(old_time, 1): #有效期：1小时，超期需要重新从数据库读取
                    if utils._utils_debug: print(f'{ck_filepath} is out of one hour, we re-get it')
                    need_to_del_ck_file_flag = True
            except Exception as e:
                if utils._utils_debug: print(f'Warn: read from {ck_filepath} failed for '
                                             f'exception([{e.__traceback__.tb_frame.f_globals["__file__"]}:'
                                             f'{e.__traceback__.tb_lineno}] {e}), we re-get it')
                need_to_del_ck_file_flag = True
    if need_to_del_ck_file_flag:
        os.remove(ck_filepath)
        if os.path.exists(db_filepath):
            os.remove(db_filepath)
        local_data = None

    if not os.path.isfile(ck_filepath):
        # local sqlite Chrome cookie database path
        db_path = get_db_path_info(select=db_select)
        if db_path is None:
            return None
        # copy file when does not exist in the current directory
        try:
            shutil.copyfile(db_path, db_filepath)
        except PermissionError as e:
            print(f'Warn: Permission denied, can\'t open {db_path}, \nyou need to close chrome or start it by `chrome.exe --disable-features=LockProfileCookieDatabase`')
            if os.path.exists(db_filepath): os.remove(db_filepath)
            return None
        except Exception as e:
            if utils._utils_debug: print(f'Error: copy from {db_path} failed for {e}')
            if os.path.exists(db_filepath): os.remove(db_filepath)
            return None
    else:
        if local_data is not None:
            if utils._utils_debug: print(f'get cookie from local {ck_filepath}'
                                         f'(extract time:{datetime.fromtimestamp(old_time).strftime("%Y-%m-%d %H:%M:%S")})')
            return local_data

    # connect to the database
    db = sqlite3.connect(db_filepath)
    # ignore decoding errors
    db.text_factory = lambda b: b.decode(errors="ignore")
    cursor = db.cursor()
    # get the cookies from `cookies` table
    domain_name = get_domain_info(select=domain_select, domain=domain)
    if domain_name != '1':
        cursor.execute(f"""
        SELECT host_key, name, value, creation_utc, last_access_utc, expires_utc, encrypted_value
        FROM cookies
        WHERE host_key like '{domain_name}' """)
    else:
        cursor.execute("""
        SELECT host_key, name, value, creation_utc, last_access_utc, expires_utc, encrypted_value 
        FROM cookies""")
        # you can also search by domain, e.g thepythoncode.com
        # cursor.execute("""
        # SELECT host_key, name, value, creation_utc, last_access_utc, expires_utc, encrypted_value
        # FROM cookies
        # WHERE host_key like '%thepythoncode.com%'""")

    # get the AES key
    key = get_encryption_key()
    for host_key, name, value, creation_utc, last_access_utc, expires_utc, encrypted_value in cursor.fetchall():
        if not value:
            decrypted_value = decrypt_data(encrypted_value, key)
        else:
            # already decrypted
            decrypted_value = value

        # update the cookies table with the decrypted value
        # and make session cookie persistent
        cursor.execute("""
        UPDATE cookies SET value = ?, has_expires = 1, expires_utc = 99999999999999999, is_persistent = 1, is_secure = 0
        WHERE host_key = ?
        AND name = ?""", (decrypted_value, host_key, name))
        dictData = {
            'Host': host_key,
            'Cookie name': name,
            'Cookie value (decrypted)': decrypted_value,
            'Creation datetime (UTC)': get_chrome_datetime(creation_utc),
            'Last access datetime (UTC)': get_chrome_datetime(last_access_utc),
            'Expires datetime (UTC)': get_chrome_datetime(expires_utc)
        }
        cookies_data.append(dictData)
    if cookies_data:
        with open(ck_filepath, 'w', encoding='utf-8') as file:
            file.write(str(cookies_data + [datetime.now().timestamp()]))
        if utils._utils_debug: print(f"Cookie is saved into {ck_filepath}")
    else:
        if utils._utils_debug: print('Error: get domain'+('('+domain+')' if (domain_select=='2' and domain is not None) else '')+' cookies failed, maybe your input domain is invalid(not exist)')
    # commit changes
    db.commit()
    # close connection
    db.close()
    if cookies_data:
        return cookies_data
    return None

def get_bilibili_cookie():
    cookies = get_cookies(db_select='1', domain_select='2', domain='.bilibili.com')
    if cookies is None:
        return None
    bili_ck = ''
    for ck in cookies:
        if ck['Cookie name'] == 'SESSDATA':
            bili_ck += f"SESSDATA={ck['Cookie value (decrypted)']}"
            break
    bili_ck += '; CURRENT_QUALITY=112' #112为高清1080p+、80为高清1080p、64为高清、32为清晰、16为流畅
    return bili_ck

if __name__ == "__main__":
    get_cookies()