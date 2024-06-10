__all__ = ['av2bv', 'bv2av']

#https://blog.csdn.net/imba_yeyi/article/details/136833496

table = "fZodR9XQDSUm21yCkr6zBqiveYah8bt4xsWpHnJE7jL5VG3guMTKNPAwcF"
s = [11, 10, 3, 8, 4, 6, 2, 9, 5, 7]
xor = 177451812

add_105 = 8728348608
add_all = 8728348608 - 2147483647 - 1 #2147483647 is constant Integer.MAX_VALUE in java

tr = {char: i for i, char in enumerate(table)}

def bv2av(bv):
    r = 0
    for i in range(6):
        r += tr[bv[s[i]]] * (58 ** i)
    add = add_105
    if r < add:
        add = add_all
    avid = (r - add) ^ xor
    return avid

def av2bv(av):
    add = add_105
    if av > 1060000000:
        add = add_all
    av = (av ^ xor) + add
    r = list('BV1  4 1 7  ')
    for i in range(6):
        r[s[i]] = table[av // (58 ** i) % 58]
    return ''.join(r)

if __name__ == "__main__":
    print(av2bv(1301648659))
    print(bv2av("BV1uu4m1g7Ej"))