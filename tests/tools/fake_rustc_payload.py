"""Inert Cargo protocol fixture. Produces text placeholders, never Rust code."""
import json
from pathlib import Path
import sys


root = Path(sys.argv[0]).resolve().parent
args = sys.argv[1:]
with (root/'fake-rustc-invocations.jsonl').open('a', encoding='utf-8') as log:
    log.write(json.dumps(args)+'\n')


def values(key):
    result = []
    for i, arg in enumerate(args):
        if arg == key:
            result.append(args[i+1])
        elif arg.startswith(key+'='):
            result.append(arg[len(key)+1:])
    return result


if args == ['-vV']:
    print('rustc 1.99.0 (000000000 2026-01-01)\nbinary: rustc\ncommit-hash: '+40*'0'+
          '\ncommit-date: 2026-01-01\nhost: x86_64-pc-windows-msvc\nrelease: 1.99.0\nLLVM version: 21.0.0')
elif values('--print'):
    for query in values('--print'):
        if query == 'file-names':
            formats = dict(bin='___.exe', rlib='lib___.rlib', dylib='___.dll', cdylib='___.dll',
                           staticlib='___.lib', **{'proc-macro': '___.dll'})
            for kind in values('--crate-type'):
                print(formats[kind])
        elif query == 'sysroot':
            print(root/'fake-sysroot')
        elif query == 'split-debuginfo':
            print('packed')
        elif query == 'crate-name':
            print('___')
        elif query == 'cfg':
            print('debug_assertions\npanic="unwind"\ntarget_arch="x86_64"\ntarget_os="windows"\n'
                  'target_env="msvc"\ntarget_endian="little"\ntarget_pointer_width="64"\n'
                  'target_family="windows"\nwindows')
        else:
            raise SystemExit('Unsupported fake compiler query')
else:
    crate = values('--crate-name')[0]
    folder = Path(values('--out-dir')[0])
    suffix = next((value.split('=', 1)[1] for value in values('-C') if value.startswith('extra-filename=')), '')
    folder.mkdir(parents=True, exist_ok=True)
    name = ('lib'+crate+suffix+'.rlib') if values('--crate-type')[0] in ('lib', 'rlib') else crate+suffix+'.exe'
    artifact = folder/name
    artifact.write_text('FAKE compiler artifact; not executable; not compiled\n')
    (folder/(crate+suffix+'.d')).write_text(str(artifact).replace('\\', '/')+':\n')
