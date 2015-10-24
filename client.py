# -*- coding: utf-8 -*-
#
# Author: jimin.huang
#
# Created Time: 2015年10月23日 星期五 11时59分48秒
#
'''
    非阻塞的smtp client实现
'''
from tornado import iostream, gen
import socket
import smtplib
import logging
from email.base64mime import body_encode

CRLF = b'\r\n'


def _get_hostname():
    fqdn = socket.getfqdn()
    if '.' not in fqdn:
        try:
            fqdn = socket.gethostbyname(fqdn)
        except socket.gaierror:
            pass
        return bytes('[{fqdn}]'.format(fqdn=fqdn))
    return bytes(fqdn)


class AsyncSMTP(object):
    def __init__(self):
        self.timeout = socket._GLOBAL_DEFAULT_TIMEOUT
        self.if_ever_ehlo = False
        self.stream = None

    @gen.coroutine
    def get_stream(self, host, port, timeout):
        '''
            一个异步方法，构造并连接socket
        '''
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM, 0)
        self.stream = iostream.IOStream(sock)
        stream = yield self.stream.connect((host, port))
        raise gen.Return(stream)

    @gen.coroutine
    def send(self, msg):
        '''
            一个异步方法，构造并写入信息
        '''
        logging.info('send: {0}'.format(msg))
        # 信息尾部加入CRLF 否则远程服务器会一直等待发送结束
        msg = b''.join((msg, CRLF))
        yield self.stream.write(msg)
        code, response = yield self.receive()
        raise gen.Return((code, response))

    @gen.coroutine
    def receive(self):
        '''
            一个异步方法，接收客户端信息
        '''
        responses = []
        logging.info('received: ')
        while True:
            # 不停的接收CRLF之前的数据直到空行或者code异常
            try:
                response = yield self.stream.read_until(CRLF)
            except socket.error, e:
                logging.exception(e)
                response = 'failed'
            finally:
                logging.info(response.strip())

            code = str(response[0:3])

            response = response.strip()

            responses.append(response[4:])

            if not code.isdigit() or response[3] in b' \r\n':
                break

        raise gen.Return((code, responses))

    @gen.coroutine
    def connect(self, host=None, port=smtplib.SMTP_PORT):
        '''
            连接SMTP服务器
        '''
        logging.info('connect to {0}:{1}'.format(host, port))
        self.stream = yield self.get_stream(host, port, self.timeout)
        code, responses = yield self.receive()
        self.host = host
        self.port = port
        raise gen.Return((code, responses))

    @gen.coroutine
    def ehlo(self):
        '''
            一个异步的ehlo方法，发送ehlo指令
            也就是在SMTP协议中表明自己身份blahblah
        '''
        # 必须要以ehlo 主机名的形式发送 确认自己身份
        # 主机名必须在DNS上有记录 否则发不出去
        hostname = _get_hostname()
        code, responses = yield self.send('ehlo [{0}]'.format(hostname))
        self.if_ever_ehlo = True

        # 简单的假设smtp邮件服务器支持auth login plain
        # 如果不支持，则warning一下，如果之后报错，请检查之前是否有这个warning
        if 'AUTH LOGIN PLAIN' not in responses:
            logging.warning('AUTH LOGIN PLAIN not in esmtp features')

        # 存入esmtp支持的feature
        self.esmtp_features = responses

    @gen.coroutine
    def login(self, username, password):
        '''
            一个异步的login方法，简单使用auth login plain登陆
        '''
        if not self.if_ever_ehlo:
            yield self.ehlo()

        # 也就是说以AUTH PLAINascii的空格{base64形式的username}ascii的空格{base64形式的password}
        request_string =\
            b' '.join(
                (
                    b'AUTH PLAIN',
                    body_encode(
                        "\0{0}\0{1}".format(
                            username,
                            password
                        ).encode('ascii'),
                        eol="",
                    ).encode('ascii'),
                )
            )

        code, responses = yield self.send(request_string)

        # 235 成功登录
        # 503 之前已经登录了
        if code in ('235', '503'):
            raise gen.Return((code, responses))
        else:
            raise smtplib.SMTPAuthenticationError(code, responses)

    @gen.coroutine
    def rset(self):
        '''
            一个异步的rset命令，重置连接session
        '''
        try:
            yield self.send('rset')
        except smtplib.SMTPServerDisconnected:
            logging.debug('SMTPServerDisconnected')

    @gen.coroutine
    def mail(self, from_addr, options):
        '''
            一个异步的mail命令，发送mail FROM 发送者地址
        '''
        # 构造发送命令
        send_str = 'mail FROM:{0} {1}'.format(
            smtplib.quoteaddr(from_addr),
            b' '.join(options),
        ).strip().encode('ascii')

        code, responses = yield self.send(send_str)

        if code != '250':
            if code == '421':
                self.close()
            else:
                yield self.rset()
            raise smtplib.SMTPSenderRefused(code, responses, from_addr)
        raise gen.Return((code, responses))

    def close(self):
        self.stream.close()
        self.stream = None

    @gen.coroutine
    def sendmail(self, from_addr, to_addrs, msg, mail_options=[],
                 rcpt_options=[]):
        # ehlo操作是必须的
        if not self.if_ever_ehlo:
            yield self.ehlo()

        # msg编码
        if isinstance(msg, basestring):
            msg = smtplib._fix_eols(msg).encode('ascii')

        # 如果feature中有size，options必须附加当前邮件大小
        if 'size' in self.esmtp_features:
            mail_options.append('size={0}'.format(len(msg)))

        # mail命令 确定发信人
        code, responses = yield self.mail(from_addr, mail_options)

        # to_addrs 单str 要转换成list 方便后面处理
        to_addrs = [to_addrs] if isinstance(to_addrs, basestring) else to_addrs
