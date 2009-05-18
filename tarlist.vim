if &enc !~? '^utf-\=8$'
  echohl ErrorMsg
  echomsg "This plugin requires that vim be using unicode for its strings."
  echohl None
endif

" Vim represents binary files in a crazy way.  I think my way is less nuts:
" File represented as latin1 transcoded into UTF-8.
" NUL is replaced with U+FEFF (BOM (which isn't in latin1)).
" Newlines are put back in their proper places.
" Before writing anything out, these conversions must be reversed.
function! BinaryRead(filepath)
  let vim_read = readfile(a:filepath, 'b')
  call map(vim_read, 'iconv(v:val, "latin1", "utf-8")')
  call map(vim_read, 'substitute(v:val, "\n", "\xEF\xBB\xBF", "g")')
  return join(vim_read, "\n")
endfunction

" Undo the changes made by BinaryRead to allow writing a binary file out.
function! BinaryWrite(binary_file, filepath)
  let vim_write = split(a:binary_file, "\n", 1)
  call map(vim_write, 'substitute(v:val, "\xEF\xBB\xBF", "\n", "g")')
  call map(vim_write, 'iconv(v:val, "utf-8", "latin1")')
  call writefile(vim_write, a:filepath, 'b')
endfunction

" Pluck a single field from the header.  Begin grabbing at the given offset,
" and grab at most len characters.  Stop earlier if you hit a character
" that's in the breakat list.
function! GrabField(record_list, offset, len, breakat)
  let rv = ""
  for i in range(a:offset, a:offset + a:len - 1)
    if index(a:breakat, a:record_list[i]) != -1
      break
    endif
    let rv .= a:record_list[i]
  endfor
  return rv
endfunction

" Returns 0 for bad checksum, 1 for good checksum, 2 for zero block.
function! CheckChecksum(record_list, checksum)
  let checksum_offset = 148
  let checksum_len = 8

  let signed_sum = 0
  let unsigned_sum = 0

  " Calculate sum of all character values
  for char in a:record_list
    let uval = char2nr(iconv(char, "utf-8", "latin1"))
    let sval = (uval <= 127 ? uval : -256 + uval)

    let signed_sum += sval
    let unsigned_sum += uval
  endfor

  if unsigned_sum == 0
    return 2
  endif

  " Recalculate with checksum fields counted as spaces
  for i in range(checksum_offset, checksum_offset + checksum_len - 1)
    let char = a:record_list[i]

    let uval = char2nr(iconv(char, "utf-8", "latin1"))
    let sval = (uval <= 127 ? uval : -256 + uval)

    let signed_sum -= sval
    let unsigned_sum -= uval

    let signed_sum += char2nr(' ')
    let unsigned_sum += char2nr(' ')
  endfor

  echomsg a:checksum . " " . signed_sum . " " . unsigned_sum

  return a:checksum == signed_sum || a:checksum == unsigned_sum
endfunction

function! ParsePosixHeader(record)
  " Blow the string up into a list of 512 one-character strings.
  " NULs will just appear as empty strings.
  let record = map(split(a:record, '\zs'), 'substitute(v:val, "\xEF\xBB\xBF", "", "g")')

  let flag = []
  let string = ['']
  let number = ['',' ']

  let dict = {}
  let dict.name     = GrabField(record,   0, 100, string)
  let dict.mode     = GrabField(record, 100,   8, number)
  let dict.uid      = GrabField(record, 108,   8, number)
  let dict.gid      = GrabField(record, 116,   8, number)
  let dict.size     = GrabField(record, 124,  12, number)
  let dict.mtime    = GrabField(record, 136,  12, number)
  let dict.chksum   = GrabField(record, 148,   8, number)
  let dict.typeflag = GrabField(record, 156,   1, flag)
  let dict.linkname = GrabField(record, 157, 100, string)
  let dict.magic    = GrabField(record, 257,   6, string)
  let dict.version  = GrabField(record, 263,   2, flag)
  let dict.uname    = GrabField(record, 265,  32, string)
  let dict.gname    = GrabField(record, 297,  32, string)
  let dict.devmajor = GrabField(record, 329,   8, number)
  let dict.devminor = GrabField(record, 337,   8, number)
  let dict.prefix   = GrabField(record, 345, 155, string)

  let check = CheckChecksum(record, str2nr(dict.chksum, 8))

  if check == 0
    throw "Record fails checksum for " . string(record)
  endif

  if check == 2
    return {} " Zero record
  endif

  return dict
endfunction

function! Test()
  let file = split(BinaryRead("/home/matt/environment.tar"), '.\{512}\zs')
  let i = 0

  let eof_count = 0

  while eof_count < 2
    let header = ParsePosixHeader(file[i])

    if header == {}
      let eof_count += 1
      continue
    else
      let eof_count = 0
    endif

    let i += 1

    let blocks = (header.size + 511) / 512

    let file_data = []

    for j in range(blocks)
      let file_data += [ file[i+j] ]
    endfor

    let i += j + 1

    if !empty(file_data)
      let file_data[-1] = matchstr(file_data[-1], '.\{' . (header.size % 512) . '}')
    endif

    echomsg "File " . header.name . " has contents " . join(file_data, '')
  endwhile
endfunction
