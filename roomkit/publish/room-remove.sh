# Runs ON THE HOST, inside the served room (ssh HOST "cd ROOM && bash -c ..." < LIST),
# or locally in tests. Reads the publish's removal list on stdin:
#   one relative path per line   a record that left the room: removed now;
#   "#ASSETS-KEEP p1 p2 ..."     every asset named by the served or the new lock;
#                                any other file under assets/ is two generations
#                                old and goes.
# A path is removed only if it is relative, has no "..", and is made of plain
# name characters, so a bad lock can never reach outside the room.
keep=""; while IFS= read -r line; do
  case "$line" in
    "#ASSETS-KEEP "*) keep=" ${line#\#ASSETS-KEEP } " ;;
    *) [[ ! "$line" =~ \.\. ]] && [[ $line =~ ^([a-zA-Z0-9._-]+/)*[a-zA-Z0-9._-]+$ ]] && rm -f -- "$line" && echo "   removed $line" ;;
  esac
done
[ -d assets ] && find assets -type f | while IFS= read -r f; do
  case "$keep" in *" $f "*) ;; *) rm -f -- "$f" && echo "   removed old asset $f" ;; esac
done
find . -mindepth 1 -type d -empty -delete
exit 0
