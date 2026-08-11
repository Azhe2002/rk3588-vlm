#!/usr/bin/env python3
"""RK3588 板端连接助手 (linaro@192.168.1.8)"""
import sys, os
import paramiko

HOST = '192.168.1.8'
USER = 'linaro'
PASS = 'rockchip'

def get_client():
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, port=22, username=USER, password=PASS, timeout=10)
    return c

def run(c, cmd, timeout=120):
    """执行命令, 返回 (exit_code, stdout, stderr)"""
    stdin, stdout, stderr = c.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode('utf-8', 'replace')
    err = stderr.read().decode('utf-8', 'replace')
    code = stdout.channel.recv_exit_status()
    return code, out, err

def sftp_put(c, local, remote):
    sftp = c.open_sftp()
    sftp.put(local, remote)
    sftp.close()

def sftp_get(c, remote, local):
    sftp = c.open_sftp()
    sftp.get(remote, local)
    sftp.close()

if __name__ == '__main__':
    c = get_client()
    code, out, err = run(c, 'uname -a; echo ---; free -h | head -2; echo ---; ls /userdata/llama/bin/ | head -20; echo ---; ls /userdata/llama/models/')
    print(out)
    if err: print('STDERR:', err[:500])
    c.close()
