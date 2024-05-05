import os, re

def get_absolute_path(relative_path):
    absolute_path = \
        os.path.normpath(os.path.join(\
        os.path.dirname(__file__), relative_path))
    absolute_path += \
        ('' if os.path.split(relative_path)[1] else '\\')
    parent_dir = os.path.dirname(absolute_path)
    if not os.path.exists(parent_dir):
        os.makedirs(parent_dir)
    return absolute_path

def find_json_dict_from_text(text, start_str=None, num=float('inf')):
    '''demo: find_json_dict_from_text('a0={"name":"celestezj"};window.name=muggledy;a="{x:4}";d={"z1":"z2", "z3":{"z4":"{z5}","z6":888}}', 'window')'''
    stack = []
    start, end = 0, 0
    json_dict = []
    if start_str != None:
        re_text = re.findall(start_str + r'[\s\S]*', text)
        text = re_text[0] if re_text else text
    for i, c in enumerate(text):
        if stack and (stack[-1] in ['"', "'"]) and (c not in ['"', "'"]):
            continue
        if c == "'":
            if stack and stack[-1] == "'":
                stack.pop()
                continue
            stack.append(c)
        elif c == '"':
            if stack and stack[-1] == '"':
                stack.pop()
                continue
            stack.append(c)
        elif c == '{':
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
