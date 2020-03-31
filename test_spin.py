import time
from common.spinner import Spinner

spinner = Spinner()

time.sleep(5)

for i in range(5):
  spinner.update("%d" % (5 - i) * 10)
  time.sleep(1)
spinner.update("ERR,Test error")
