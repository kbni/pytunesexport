#!/usr/bin/env python

import plistlib
import urlparse, urllib2
import marshal
import shutil
import time
import sys
import os
import re

def unurlize(url):
    return urllib2.unquote(urlparse.urlsplit(url)[2])

def unfuck_path(path, trim_markers = []):
    if trim_markers:
        for trim_marker in trim_markers:
            p = path.find(trim_marker)
            if p > -1:
                path = path[p+len(trim_marker):]
    return path

def strip_bad_fn_chars(string, BAD = '\',\:*?;"<>|/'):
    for c in BAD: string = string.replace(c, '')
    return string.replace('&','+')+'.m3u'

def usage(stream):
    stream.write("pyTunesExport v0.1\n")
    stream.write("  -help       display this help page\n")
    stream.write("  -verbose    be verbose about file operations, errors printed at end\n")
    stream.write("  -halt       halt on IO error\n")
    stream.write("\n")
    stream.write("  operations..\n")
    stream.write("    -pretend    only pretend to do file operations\n")
    stream.write("    -m3u        output playlists\n")
    stream.write("    -copy       copy tracks from playlists\n")
    stream.write("    -links      or symlink them instead\n")
    stream.write("    -list       list all tracks (and their paths)\n")
    stream.write("    -clear      clear the cache before working\n")
    stream.write("    -dirs       create a directory for each plalist\n")
    stream.write("    -delete     delete orphaned mp3s\n")
    stream.write("\n")
    stream.write("  playlist selection..\n")
    stream.write("    playlists are first filtered with -skip, then added back in -keep\n")
    stream.write("    both of these options can be used multiple times (multiple regexes)\n")
    stream.write("    -keep <s>   keep playlists that match regex <s>\n")
    stream.write("    -skip <s>   skip playlists that match regex <s>\n")
    stream.write("    -test       show skip/keep results then quit\n")
    stream.write("\n")
    stream.write("  file/path manipulation..\n")
    stream.write("    -xml <f>    load <f> instead of iTunes Music Libary.xml\n")
    stream.write("                (defaults to $HOME/Music/iTunes/iTune Music Library.xml)\n")
    stream.write("    -trim <s>   trim <s> and everything before it for output file paths\n")
    stream.write("                (can specify multiple trims)\n")
    stream.write("    -prep <s>    put <s> before the file path (in playlists only)\n")
    stream.write("    -out <d>    cd to <d> before performing file operations\n")
    return int(stream==sys.stderr) 

def main(argv):
    def get_flag(flag, has_arg=False, default=False):
        flag = '-' + flag
        if flag not in argv:
            if has_arg:
                return default
            return False
        else:
            i = argv.index(flag)
            argv.remove(flag)
            if has_arg:
                val = argv[i]
                argv.remove(val)
                return val
            return True

    def get_loop(flag):
        ret = []
        while True:
            got = get_flag(flag, True)
            if got:
                ret.append(got)
            else:
                break
        return ret

    output_playlists = get_flag('m3u')
    copy_tracks = get_flag('copy')
    symlink_tracks = get_flag('links')
    xml_file = get_flag('xml', True, '%s/Music/iTunes/iTunes Music Library.xml' % os.environ.get('HOME'))
    cache_file = get_flag('temp', True, '%s/pytunesexport.cache' % os.environ.get('TMPDIR'))
    output_dir = get_flag('out', True, os.getcwd())
    verbose = get_flag('verbose')
    fake_operation = get_flag('pretend')
    halt_on_ioerr = get_flag('halt')
    trim_markers = get_loop('trim')
    skip_playlists = [ re.compile(r) for r in get_loop('skip') ]
    keep_playlists = [ re.compile(r) for r in get_loop('keep') ]
    test_playlists = get_flag('test')
    list_tracks = get_flag('list')
    clear_cache = get_flag('clear')
    delete_orphans = get_flag('delete')
    directory_playlist = get_flag('dirs')

    if get_flag('help') or get_flag('h'):
        return usage(sys.stdout)

    if len(argv) > 1:
        sys.stderr.write("Extra options: %s\n\n" % ', '.join(argv[1:]))
        return usage(sys.stderr)
    
    if not os.path.exists(xml_file):
        sys.stderr.write("library file (%s) does not exist!\n" % (library_file,))
        return 1
    
    if symlink_tracks and copy_tracks:
        sys.stderr.write("can't symlink and copy the tracks\n")
        return 1
    
    if os.path.exists(cache_file) and not clear_cache:
        print 'Reading library from cache.'
        fh = open(cache_file, 'r+b')
        playlists = marshal.load(fh)
        fh.close()
    else:
        print 'Reading library & writing cache.'
        xml = plistlib.readPlist(xml_file)
        fh = open(cache_file, 'w+b')
        playlists = []
        tracks = {}
        for p in xml['Playlists']:
            items = []
            if not p.has_key('Distinguished Kind') and p.has_key('Playlist Items'):
                for t in p['Playlist Items']:
                    track_id = '%s'%t['Track ID']
                    if not tracks.has_key(track_id):
                        tracks[track_id] = unurlize(xml['Tracks'][track_id]['Location'])
                    items.append(tracks[track_id])
                playlists.append((p['Name'], items))
        marshal.dump(playlists, fh)
        fh.close()

    if not playlists:
        sys.stderr.write("there are no playlists!\b")
        sys.exit(1)
    
    use_playlists = [ (p[0],playlists.index(p)) for p in playlists
            if sum([ len(_.findall(p[0])) for _ in skip_playlists ]) == 0
            or sum([ len(_.findall(p[0])) for _ in keep_playlists ])  > 0 ]

    if test_playlists:
        print 'The following playlists to be used:'
        for name, idx in use_playlists:
            print '  %s - %d tracks' % (name, len(playlists[idx][1]))
        return 0

    map_paths = []
    
    for name, playlist_idx in use_playlists:
        tracks_fn = []
        for full_path in playlists[playlist_idx][1]:
            rel_path = unfuck_path(full_path, trim_markers)
            if directory_playlist:
                bn = '%04d.%s' % (len(tracks_fn)+1, os.path.basename(rel_path))
                rel_path = os.path.join(output_dir, name, bn)
            else:
                rel_path = os.path.join(output_dir, rel_path)
            tracks_fn.append(rel_path.replace(output_dir,'')[1:])
            map_paths.append((full_path,rel_path))

        m3u_txt = ""
        for track_fn in tracks_fn:
            m3u_txt += "%s\r\n" % track_fn.decode("utf-8")
        m3u_fn = os.path.join(output_dir, strip_bad_fn_chars(name))
        
        if output_playlists:
            if verbose or fake_operation:
                print "writing playlist %s (%d tracks)" % (m3u_fn, len(tracks_fn))
            if not fake_operation:
                m3u_fh = open(m3u_fn, 'w')
                m3u_fh.write(m3u_txt.encode('utf-8'))
                m3u_fh.close()

    if list_tracks:
        for (full_path, rel_path) in map_paths:
            print
            print os.path.basename(rel_path)
            print full_path
            print rel_path
            
    if copy_tracks or symlink_tracks:
        err_log = []
        made_dirs = []
        for (full_path, rel_path) in map_paths:
            if os.path.exists(rel_path):
                if verbose:
                    print "exists: %s" % (rel_path,)
            else:
                dest_path = os.path.dirname(rel_path)
                if not os.path.exists(dest_path):
                    if not fake_operation: os.makedirs(dest_path)
                    if verbose and dest_path not in made_dirs:
                        print "mkdir -p '%s'" % (dest_path,)
                        made_dirs.append(dest_path)
                if copy_tracks:
                    try:
                        if not fake_operation: shutil.copy(full_path, rel_path)
                        if verbose: print "cp '%s' '%s'" % (full_path, rel_path)
                    except IOError, e:
                        err = str(e).split('] ',1)[-1]
                        if halt_on_ioerr:
                            sys.stderr.write(err + "\n")
                            return 1
                        print err
                        err_log.append(err)
                if symlink_tracks:
                    if not fake_operation: os.symlink(full_path, rel_path)
                    if verbose: print "ln -s '%s' '%s'" % (full_path, rel_path)
        if err_log:
            if verbose:
                for err in err_log:
                    sys.stderr.write(err + "\n")
                    sys.stderr.flush()
            sys.stderr.write("%d errors occured" % len(err_log))
        
    return 0
                
if __name__ == "__main__":
    sys.exit(main(sys.argv))
