# Assembles index.html = shared frame head (frame_head.html: styles / filters / animation helpers) + this episode's main.js
import os
os.chdir(os.path.dirname(os.path.abspath(__file__)))
head = open('frame_head.html', encoding='utf-8').read()
open('index.html', 'w', encoding='utf-8').write(head + '\n' + open('main.js', encoding='utf-8').read() + '\n</script>\n</body>\n</html>\n')
print('ok', head.count('\n'))
