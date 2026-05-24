import ast, sys
files = ['config.py', 'core/terrain.py', 'main.py']
all_ok = True
for f in files:
    try:
        with open(f, encoding='utf-8') as fh: src = fh.read()
        ast.parse(src)
        print(f'  OK  {f}')
    except SyntaxError as e:
        print(f'  FAIL {f}: line {e.lineno}: {e.msg}')
        all_ok = False
    except FileNotFoundError:
        print(f'  MISS {f}')
        all_ok = False
sys.exit(0 if all_ok else 1)
