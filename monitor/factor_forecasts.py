"""Public dated forecast observations for the reference panel only."""
from html.parser import HTMLParser
import re
from urllib.parse import urljoin, urlparse

import pandas as pd
from macro_sources import request

FACTSET='https://insight.factset.com/topic/earnings'


class Page(HTMLParser):
    def __init__(self):
        super().__init__();self.text=[];self.links=[];self.hidden=0;self.heading=0

    def handle_starttag(self,tag,attrs):
        attrs=dict(attrs)
        if tag in ('script','style'):self.hidden+=1
        if tag=='h2':self.heading+=1
        if tag=='a' and self.heading and attrs.get('href'):
            url=urljoin(FACTSET,attrs['href'])
            if urlparse(url).hostname=='insight.factset.com' and '/topic/' not in url:
                self.links.append(url)

    def handle_endtag(self,tag):
        if tag in ('script','style'):self.hidden=max(0,self.hidden-1)
        if tag=='h2':self.heading=max(0,self.heading-1)

    def handle_data(self,data):
        if not self.hidden:self.text.append(data)


def parse_article(body,url,at):
    page=Page();page.feed(body);text=re.sub(r'\s+',' ',' '.join(page.text))
    stamp=re.search(r'\b(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},\s+20\d{2}',text)
    if not stamp:raise ValueError('未识别报告日期')
    date=pd.Timestamp(stamp[0]);today=at.tz_convert('America/New_York').tz_localize(None).normalize()
    if date>today:raise ValueError('报告日期晚于今天')
    pe=re.search(r'forward\s+12\s*[-–]\s*month P/E ratio (?:for the S&P 500 )?is (\d+(?:\.\d+)?)',text,re.I)
    result={}
    if pe:
        value=float(pe[1])
        if not 1<=value<=200:raise ValueError('前瞻PE不合理')
        result['valuation']={'date':str(date.date()),'values':{'pe':value},'scope':'S&P500 前瞻12个月',
                             'source':url,'method':'公开报告自动提取'}
    # Only explicit per-share estimates, never actual EPS or growth-rate changes.
    revision=re.search(r'On a per.share basis, estimated earnings for the (first|second|third|fourth) quarter '
        r'(?:have |has )?(fallen|declined|decreased|dropped|increased|risen) by (\d+(?:\.\d+)?)% '
        r'(?:since|from) (December 31|March 31|June 30|September 30)',text,re.I)
    if revision:
        quarter=['first','second','third','fourth'].index(revision[1].lower())+1
        expected=['December 31','March 31','June 30','September 30'][quarter-1]
        if revision[4].lower()!=expected.lower():raise ValueError('预测季度与修订起点不一致')
        year_match=re.search(r'earnings estimates for Q'+str(quarter)+r' (20\d{2})',text,re.I)
        if year_match:
            value=float(revision[3])*(1 if revision[2].lower() in ('increased','risen') else -1)
            if not -100<=value<=100:raise ValueError('EPS修订不合理')
            result['earnings']={'date':str(date.date()),'values':{'quarter_revision':value},
                'scope':f'S&P500 {year_match[1]} Q{quarter}；自{expected}开始的季内预测修正',
                'source':url,'method':'公开报告自动提取；不是固定1月或3月修订'}
    return result


def fetch(at,previous=None):
    previous=previous or {};page=Page();page.feed(request(FACTSET,read_timeout=15).text)
    links=list(dict.fromkeys(page.links))[:4]
    if not links:raise ValueError('未找到公开报告链接')
    observations={};failures=0
    for url in links:
        try:
            found=parse_article(request(url,read_timeout=15).text,url,at)
            for kind,row in found.items():
                if kind not in observations or row['date']>observations[kind]['date']:observations[kind]=row
            if len(observations)==2:break
        except Exception:failures+=1
    if not observations:raise ValueError('公开报告暂无可核对的PE或EPS修订')
    # Never erase a previously verified observation just because a new article
    # lacks that field. Each field retains its own publication date and source.
    for kind in ('valuation','earnings'):
        old=previous.get(kind)
        if old and (kind not in observations or old['date']>observations[kind]['date']):observations[kind]=old
    return {**observations,'source':FACTSET,'partial_failures':failures}
