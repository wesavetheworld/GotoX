# coding:utf-8
'''Auto check and update GAE IP'''

import threading
from . import clogging as logging
from time import time, sleep, strftime
from .compat import thread, Queue
from .common import config_dir
from .GlobalConfig import GC
from .ProxyServer import network_test
from .HTTPUtil import http_gws
from .GAEFinder import (
    g as finder,
    g_comdomain as comdomain,
    timeToDelay,
    writebytes,
    gae_finder,
    getgaeip,
    savestatistics,
    #savebadlist
    )

lLock = threading.Lock()
tLock = threading.Lock()

class testip:
    running = False
    queobj = Queue.Queue()
    lastactive = lastupdate = time()
    lasttest = lastupdate - 30

def removeip(ip):
    with lLock:
        for name in GC.IPLIST_MAP:
            if name.startswith('google_'):
                try:
                    GC.IPLIST_MAP[name].remove(ip)
                except:
                    pass

def _refreship(gaeip):
    with lLock:
        for name in gaeip:
            GC.IPLIST_MAP[name][:] = gaeip[name] + GC.IPLIST_MAP[name]
    testip.lastupdate = time()

ipuse_h = ('#coding: utf-8\n'
           '#此文件由 GotoX 自动维护，请不要修改。\n'
           '[iplist]\n').encode()

def refreship(needgws=None, needcom=None):
    threading.current_thread().setName('Find GAE')
    #检测当前 IP 并搜索新的 IP
    network_test()
    if needgws is None:
        needgws = countneedgws()
    if needcom is None:
        needcom = countneedcom()
    gaeip = getgaeip(GC.IPLIST_MAP['google_gws'], needgws, needcom)
    #更新 IP
    if gaeip and gaeip['google_gws']:
        _refreship(gaeip)
        #更新 ip.use
        with open(GC.CONFIG_IPDB, 'wb') as f:
            write = writebytes(f.write)
            f.write(ipuse_h)
            for name in gaeip:
                write(name)
                f.write(b' = ')
                write('|'.join(GC.IPLIST_MAP[name]))
                f.write(b'\n')
        logging.test('GAE IP 更新完毕')
    if len(GC.IPLIST_MAP['google_gws']) < GC.FINDER_MINIPCNT:
        logging.warning('没有检测到足够数量符合要求的 GAE IP，请重新设定参数！')
    #更新完毕
    updateip.running = False

def updateip(needgws=None, needcom=None):
    with tLock:
        if updateip.running: #是否更新
            return
        updateip.running = True
    thread.start_new_thread(refreship, (needgws, needcom))
updateip.running = False

timeoutb = max(GC.FINDER_MAXTIMEOUT*1.3, 1000)
def gettimeout():
    timeout = timeoutb + min(len(GC.IPLIST_MAP['google_gws']), 20)*10 + timeToDelay[strftime('%H')]
    return int(timeout)

def countneedgws():
    return max(GC.FINDER_MINIPCNT - len(GC.IPLIST_MAP['google_gws']), 0)

ipcomcnt = max(min(GC.FINDER_MINIPCNT//3, 5), 1)
def countneedcom():
    return max(ipcomcnt - len(GC.IPLIST_MAP['google_com']), 0)

def testipuseable(ip):
    _, _, isgaeserver = gae_finder.getipinfo(ip)
    if not isgaeserver:
        removeip(ip)
        addtoblocklist(ip)
        logging.warning('IP：%r 暂时不可用，已经删除', ip)
    return isgaeserver

if GC.GAE_USEGWSIPLIST:
    def addtoblocklist(ip):
        timesdel = finder.baddict[ip][2] if ip in finder.baddict else 0
        finder.baddict[ip] = GC.FINDER_TIMESBLOCK+1, int(time()), timesdel+1
        for ipdict in finder.statistics:
            if ip in ipdict:
                ipdict[ip] = -1, 0
        #finder.reloadlist = True

    def testallgaeip(force=False):
        with tLock:
            if updateip.running:
                return
            elif force:
                if testip.running == 9:
                    return
                while testip.running == 1:
                    sleep(0.1)
            elif testip.running:
                return
            testip.running = 9
        thread.start_new_thread(_testallgaeip, ())
        return True
else:
    def dummy(*args, **kwargs):
        pass

    addtoblocklist = testallgaeip = dummy

def _testallgaeip():
    iplist = GC.IPLIST_MAP['google_gws']
    if not iplist:
        testip.running = False
        return updateip()
    badip = set()
    timeout = gettimeout()
    logging.test('连接测试开始，超时：%d 毫秒', timeout)
    network_test()
    testip.queobj.queue.clear()
    for ip in iplist:
        thread.start_new_thread(http_gws._create_ssl_connection, ((ip, 443), 'google_gws:443', None, testip.queobj, timeout/1000))
    for _ in iplist:
        result = testip.queobj.get()
        if isinstance(result, Exception):
            ip = result.xip[0]
            logging.warning('测试失败 %s：%s' % ('.'.join(x.rjust(3) for x in ip.split('.')), result.args[0]))
            badip.add(ip)
        else:
            logging.test('测试连接 %s: %d' %('.'.join(x.rjust(3) for x in result[0].split('.')), int(result[1]*1000)))
    #删除 bad IP
    nbadip = len(badip)
    if nbadip > 0:
        for ip in badip:
            removeip(ip)
    logging.test('连接测试完毕%s', '，Bad IP 已删除' if nbadip > 0 else '')
    testip.lastactive = testip.lasttest = time()
    testip.running = False
    #刷新开始
    needgws = countneedgws()
    needcom = countneedcom()
    if needgws > 0 or needcom > 0:
        updateip(needgws, needcom)

def testonegaeip():
    with tLock:
        if updateip.running or testip.running:
            return
        testip.running = 1
    ip = GC.IPLIST_MAP['google_gws'][-1]
    timeout = gettimeout()
    badip = False
    statistics = finder.statistics
    network_test()
    testip.queobj.queue.clear()
    http_gws._create_ssl_connection((ip, 443), 'google_gws:443', None, testip.queobj, timeout/1000)
    result = testip.queobj.get()
    if isinstance(result, Exception):
        logging.warning('测试失败（超时：%d 毫秒）%s：%s，Bad IP 已删除' % (timeout,  '.'.join(x.rjust(3) for x in ip.split('.')), result.args[0]))
        removeip(ip)
        badip = True
        ipdict, ipdicttoday = statistics
        if ip in ipdict:
            good, bad = ipdict[ip]
            #失败次数超出预期，设置 -1 表示删除
            s = bad/max(good, 1)
            if s > 2 or (s > 0.4 and bad > 10):
                ipdict[ip] = ipdicttoday[ip] = -1, 0
            else:
                ipdict[ip] = good, bad + 1
                if ip in ipdicttoday:
                    good, bad = ipdicttoday[ip]
                else:
                    good = bad = 0
                ipdicttoday[ip] = good, bad + 1
        #加入统计
        else:
            ipdict[ip] = ipdicttoday[ip] = 0, 1
    else:
        logging.test('测试连接（超时：%d 毫秒）%s: %d' %(timeout,  '.'.join(x.rjust(3) for x in result[0].split('.')), int(result[1]*1000)))
        GC.IPLIST_MAP['google_gws'].insert(0, GC.IPLIST_MAP['google_gws'].pop())
        #调高 com 权重
        addn = 2 if ip in GC.IPLIST_MAP['google_com'] else 1
        baddict = finder.baddict
        for ipdict in statistics:
            if ip in ipdict:
                good, bad = ipdict[ip]
                good += addn
                ipdict[ip] = good, bad
                #当天通过测试次数达到条件后重置容忍次数
                if ipdict is statistics[1] and ip in baddict:
                    s = bad/max(good, 1)
                    if s < 0.1:
                        del baddict[ip]
            #加入统计
            else:
                ipdict[ip] = addn, 0
    savestatistics()
    testip.lasttest = time()
    testip.running = False
    #刷新开始
    needgws = countneedgws()
    needcom = countneedcom()
    if needgws > 0 or needcom > 0:
        updateip(needgws, needcom)
    elif badip:
        testonegaeip()

def testipserver():
    #启动时全部测一遍
    testallgaeip()
    looptime = max(120, GC.GAE_KEEPTIME)
    while True:
        now = time()
        lasttest = now - testip.lasttest
        try:
            if ((now - testip.lastactive > 6 or # X 秒钟未使用
                    lasttest > 30) and  #强制 X 秒钟检测
                    #and not GC.PROXY_ENABLE              #无代理
                    lasttest > looptime/(len(GC.IPLIST_MAP['google_gws']) or 1)): #强制 x 秒间隔
                testonegaeip()
        except Exception as e:
            logging.exception(' IP 测试守护线程错误：%r', e)
        finally:
            sleep(2)

def checkgooglecom():
    def _checkgooglecom(ssldomain, costtime, isgaeserver):
        if ssldomain == comdomain:
            ssldomain = '*.google.com'
        else:
            with lLock:
                try:
                    GC.IPLIST_MAP['google_com'].remove(ip)
                except:
                    pass
        logging.test('固定 GAE IP 列表检测，IP：%s，可用证书：%s，耗时：%d 毫秒，支持 GAE：%s',
                     ip, ssldomain, costtime, bool(isgaeserver))

    retrylist = []
    retrytimes = 2
    for ip in GC.IPLIST_MAP[GC.GAE_IPLIST]:
        ssldomain, costtime, isgaeserver = gae_finder.getipinfo(ip)
        if ssldomain is None:
            retrylist.append(ip)
        else:
            _checkgooglecom(ssldomain, costtime, isgaeserver)
    for i in range(retrytimes):
        for ip in retrylist.copy():
            ssldomain, costtime, isgaeserver = gae_finder.getipinfo(ip, 3, 3, 4)
            if i == retrytimes - 1:
                _checkgooglecom(ssldomain, costtime, isgaeserver)
            elif ssldomain is not None:
                retrylist.remove(ip)
                _checkgooglecom(ssldomain, costtime, isgaeserver)
    countcom = len(GC.IPLIST_MAP['google_com'])
    if countcom < 3:
        logging.error('检测出固定 GAE IP 列表 [%s] 中包含的可用 GWS IP 数量过少：%d 个，请增加。', GC.GAE_IPLIST, countcom)
