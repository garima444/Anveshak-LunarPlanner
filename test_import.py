import sys, os
sys.path.insert(0, '.')
os.chdir(os.path.dirname(os.path.abspath(__file__)))
try:
    import main
    print('main imported OK')
    print(f'Routes: {len(main.app.routes)}')
except Exception as e:
    import traceback
    print(f'IMPORT ERROR: {e}')
    traceback.print_exc()
