from cx_Freeze import setup,Executable

excludes = ['Tkinter']
packages = ['json']

setup(
    name = 'rip3',
    version = '3.0',
    description = 'A general downloader utility',
    author = '',
    author_email = '',
    options = {'build_exe': {'excludes':excludes,    
    'packages':packages,
    'include_files':['py', 'index.html', 'api.cgi', 'README.md', 'ui']}}, 
    executables = [Executable('serve.py'), Executable('RipManager.py'), Executable('StatusManager.py'), Executable('api.cgi')]
)
