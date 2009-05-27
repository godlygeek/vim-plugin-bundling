" Pluck a single field from the header.  Begin grabbing at the given offset,
" and grab at most len characters.  Stop earlier if you hit a character
" that's in the breakat list.
"
" record_list is a List of 512 characters
" offset and len are Numbers
" breakat is a List of any number of elements
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

" Calculate the checksum for a header and compare it to the encoded checksum.
"
" record_list is a List of 512 characters.
"
" The encoded checksum is an octal number, encoded in ascii, in bytes 148:155
"
" Calculates both the unsigned checksum and the signed one (for buggy tars).
" Returns 0 for bad checksum, 1 for good checksum, 2 for zero block.
function! CheckChecksum(record_list)
  let cs_offset = 148
  let cs_len = 8

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
  for i in range(cs_offset, cs_offset + cs_len - 1)
    let char = a:record_list[i]

    let uval = char2nr(iconv(char, "utf-8", "latin1"))
    let sval = (uval <= 127 ? uval : -256 + uval)

    let signed_sum -= sval
    let unsigned_sum -= uval

    let signed_sum += char2nr(' ')
    let unsigned_sum += char2nr(' ')
  endfor

  let encoded_chksum = GrabField(a:record_list, cs_offset, cs_len, [''])
  let checksum = str2nr(encoded_chksum, 8)

  "echomsg checksum . " " . signed_sum . " " . unsigned_sum

  return checksum == signed_sum || checksum == unsigned_sum
endfunction

" Given a 512 element long List of single character Strings, parse it into
" fields as a tar header.
"
" The return value will be a dictionary with keys for each field.  The type of
" header it is recognized to be will be stored in the format field.  If
" a field has a numeric value a Number will be stored, if it has a string
" value a String will be stored, otherwise a List of single-character strings
" will be stored.
"
" If the List contained only NUL strings, return {} to signal an empty header.
function! ParseHeaderList(record)
  let record = a:record

  if len(record) != 512
    throw "Header is the wrong size!"
  endif

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
  let dict.typeflag = record[156 : 156]
  let dict.linkname = GrabField(record, 157, 100, string)
  let dict.magic    = GrabField(record, 257,   6, string)
  let dict.version  = record[263 : 264]

  " format is one of [ oldgnu, ustar, v7 ]
  " [ gnu, pax, star ] are not supported (yet?)
  let dict.format = 'v7'
  if dict.magic == 'ustar'
    let dict.format = 'ustar'
  elseif dict.magic == 'ustar ' && dict.version == [ ' ', '' ]
    let dict.format = 'oldgnu'
  endif

  if dict.format ==# 'v7'
    " These fields, and all after them, should be NUL in v7 archives
    unlet dict.magic
    unlet dict.version
  elseif dict.format ==# 'ustar' || dict.format ==# 'oldgnu'
    let dict.uname    = GrabField(record, 265,  32, string)
    let dict.gname    = GrabField(record, 297,  32, string)
    let dict.devmajor = GrabField(record, 329,   8, number)
    let dict.devminor = GrabField(record, 337,   8, number)
    if dict.format ==# 'ustar'
      let dict.prefix   = GrabField(record, 345, 155, string)
    elseif dict.format ==# 'oldgnu'
      let dict.atime       = GrabField(record, 345, 12, number)
      let dict.ctime       = GrabField(record, 357, 12, number)
      let dict.offset      = GrabField(record, 369, 12, number)
      let dict.longnames   = record[381 : 384]
      let dict.sp          = record[386 : 481]
      let dict.is_extended = record[482 : 482]
      let dict.realsize    = GrabField(record, 483, 12, number)

      if len(filter(copy(dict.sp), 'strlen(v:val)'))
            \ || strlen(dict.is_extended[0])
            \ || dict.realsize > 0
        throw "Can't support sparse files or parse tarballs using them!"
      endif
    endif
  endif

  if dict.typeflag == [ 'S' ]
    throw "Can't support sparse files or parse tarballs using them!"
  endif

  let check = CheckChecksum(record)

  if check == 0
    throw "Record fails checksum for " . string(record)
  endif

  if check == 2
    return {} " Zero record
  endif

  return dict
endfunction

function! ReadBytes(read_file, num_bytes)
  let len = 0
  let data = []
  let line_has_nl = 0

  while 1
    let line_has_nl = (len(a:read_file) > 1)

    if len(a:read_file) == 0 || len + len(a:read_file[0]) + line_has_nl > a:num_bytes
      break " Can't read a whole line; only need part of it.
    endif

    let len += len(a:read_file[0]) + line_has_nl
    let data += [ remove(a:read_file, 0) ]

    " If there should be a newline, and it was the last needed byte, add it
    if line_has_nl && len == a:num_bytes
      let data += [ '' ]
    endif
  endwhile

  if !empty(a:read_file)
    let rest = a:num_bytes - len

    if rest > 0
      let data += [ a:read_file[0][: rest-1] ]
      let a:read_file[0] = a:read_file[0][rest :]
    endif
  endif

  return data
endfunction

function! VimReadfileToList(read_file)
  let list = []
  for i in range(len(a:read_file))
    let line = a:read_file[i]

    for j in range(len(line))
      let char = line[j]
      if char == "\n"
        let list += [ "" ]
      else
        let list += [ char ]
      endif
    endfor

    if i != len(a:read_file) - 1
      let list += [ "\n" ]
    endif
  endfor

  return list
endfunction

function! HandleUnsupportedFeatures(state, header_dict)
  let dict = a:header_dict
  let state = a:state

  echohl WarningMsg

  " FIXME Warn about 'mode' not being restorable

  if !has_key(state, 'uid_disabled')
    if has_key(state, 'uid') && dict.uid != state.uid
      echomsg "Cannot extract files with different ownership."
      echomsg "Files archived for UID " . state.uid . " and " . dict.uid
          \ . " will both be owned by the current user."
    endif
  endif

  let state.uid = dict.uid

  if !has_key(state, 'gid_disabled')
    if has_key(state, 'gid') && dict.gid != state.gid
      echomsg "Cannot extract files with different ownership."
      echomsg "Files archived for GID " . state.gid . " and " . dict.gid
          \ . " will both be owned by the current group."
    endif
  endif

  let state.gid = dict.gid

  if dict.typeflag[0] !~ '^[05]\=$'
    echomsg "Unknown/unsupported typeflag " . dict.typeflag[0]
    echomsg "Treating '" . dict.name . "' as a regular file."
  endif

  if has_key(dict, 'offset') && dict.offset != 0
    echomsg "Ignoring offset into multi-volume archive"
  endif

  echohl None
endfunction

" Given a binary file returned from readfile(), parse it into headers and
" corresponding file contents.
"
" Issue warnings whenever a header wants some behavior that isn't possible.
function! GetTarHeaders(read_file)
  let rv = []
  let eof_count = 0

  let warn_state = {}

  while eof_count < 2
    let header_readfile = ReadBytes(a:read_file, 512)
    let header_list = VimReadfileToList(header_readfile)

    let header = ParseHeaderList(header_list)

    if header == {}
      let eof_count += 1
      continue
    else
      if eof_count > 0
        echohl WarningMsg
        echomsg "Empty header encountered before end of archive."
        echohl None
      endif
      let eof_count = 0
    endif

    call HandleUnsupportedFeatures(warn_state, header)

    if header.typeflag == [ '5' ]
      " Ignore size header for directories
      let blocks = 0
      let skip = 0
    else
      " Calculate number of bytes use as file contents and to skip
      let blocks = (header.size + 511) / 512
      let skip = 512 * blocks
    endif

    let file_data = ReadBytes(a:read_file, header.size)

    " throw away padding NULs
    call ReadBytes(a:read_file, skip - header.size)

    let rv += [ [header, file_data] ]
  endwhile

  return rv
endfunction

function! UnpackTarFile(read_file, where)
  " FIXME Definitely some escaping concerns here...
  let where = a:where
  if where !~ '/$'
    let where .= '/'
  endif

  call system("rm -rf " . where)
  call mkdir(where)

  for [ header, file_data ] in GetTarHeaders(a:read_file)
    if header.typeflag == [ '5' ]
      call mkdir(where . header.name)
    else
      let dir = fnamemodify(where . header.name, ":p:h")
      if !isdirectory(dir)
        call mkdir(dir, "p")
      endif
      call writefile(file_data, where . header.name, "b")
    endif

    "echomsg "File " . header.name . " has contents " . join(file_data, '')
  endfor
endfunction

function! TestTarHandling()
  call UnpackTarFile(readfile(path_to_test_tar, "b"), dest_directory)
endfunction
