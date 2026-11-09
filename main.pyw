# Starts Homework Lock without a console window (.pyw files run with pythonw.exe).
# Also the entry point of the packaged HomeworkLock.exe, which runs its helpers through flags.
import sys

if __name__ == "__main__":
    if len(sys.argv) >= 4 and sys.argv[1] == "--watchdog":
        from homework_lock.watchdog import watch
        watch(int(sys.argv[2]), float(sys.argv[3]))
    elif len(sys.argv) >= 4 and sys.argv[1] == "--finish-update":
        from homework_lock.updater import finish_update
        finish_update(sys.argv[2], sys.argv[3])
    elif len(sys.argv) >= 2 and sys.argv[1] == "--autostart":
        from homework_lock.autostart import main
        main()
    else:
        from homework_lock.app import main
        main()
