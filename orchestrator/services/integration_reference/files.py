"""Windows local-file adapter: pinned directory chain and one validated read handle.

No Path.resolve security claims. Deny unsupported OS, UNC/device paths, reparse points,
hardlinks, alternate data streams and concurrent write/delete handles. Trusted M1 code
selects the root; Authority.read_file performs identity/grant/version checks first.
"""
from contextlib import ExitStack, contextmanager
from pathlib import Path, PureWindowsPath
import ctypes, os
from .authority import Denied, require, safe_name

if os.name == 'nt':
    from ctypes import wintypes as w
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    class Info(ctypes.Structure):
        _fields_=[('attributes',w.DWORD),('created',w.FILETIME),('access',w.FILETIME),('written',w.FILETIME),
                  ('volume',w.DWORD),('size_high',w.DWORD),('size_low',w.DWORD),('links',w.DWORD),
                  ('index_high',w.DWORD),('index_low',w.DWORD)]
    kernel.CreateFileW.argtypes=[w.LPCWSTR,w.DWORD,w.DWORD,w.LPVOID,w.DWORD,w.DWORD,w.HANDLE]
    kernel.CreateFileW.restype=w.HANDLE
    kernel.GetFileInformationByHandle.argtypes=[w.HANDLE,ctypes.POINTER(Info)]
    kernel.GetFileInformationByHandle.restype=w.BOOL
    kernel.GetFinalPathNameByHandleW.argtypes=[w.HANDLE,w.LPWSTR,w.DWORD,w.DWORD]
    kernel.GetFinalPathNameByHandleW.restype=w.DWORD
    kernel.GetFileType.argtypes=[w.HANDLE];kernel.GetFileType.restype=w.DWORD
    kernel.ReadFile.argtypes=[w.HANDLE,w.LPVOID,w.DWORD,ctypes.POINTER(w.DWORD),w.LPVOID]
    kernel.ReadFile.restype=w.BOOL
    kernel.CloseHandle.argtypes=[w.HANDLE];kernel.CloseHandle.restype=w.BOOL
    kernel.GetDriveTypeW.argtypes=[w.LPCWSTR];kernel.GetDriveTypeW.restype=w.UINT
    kernel.GetVolumeInformationW.argtypes=[w.LPCWSTR,w.LPWSTR,w.DWORD,w.LPVOID,w.LPVOID,w.LPVOID,w.LPWSTR,w.DWORD]
    kernel.GetVolumeInformationW.restype=w.BOOL
    class UnicodeString(ctypes.Structure):
        _fields_=[('length',w.USHORT),('maximum',w.USHORT),('buffer',w.LPWSTR)]
    class ObjectAttributes(ctypes.Structure):
        _fields_=[('length',w.ULONG),('root',w.HANDLE),('name',ctypes.POINTER(UnicodeString)),
                  ('attributes',w.ULONG),('security',w.LPVOID),('quality',w.LPVOID)]
    class IOStatus(ctypes.Structure):
        _fields_=[('status',ctypes.c_void_p),('information',ctypes.c_size_t)]
    native=ctypes.WinDLL('ntdll')
    native.NtCreateFile.argtypes=[ctypes.POINTER(w.HANDLE),w.ULONG,ctypes.POINTER(ObjectAttributes),
        ctypes.POINTER(IOStatus),w.LPVOID,w.ULONG,w.ULONG,w.ULONG,w.ULONG,w.LPVOID,w.ULONG]
    native.NtCreateFile.restype=ctypes.c_long


class WindowsAssetReader:
    def __init__(self, root, *, max_bytes=16*1024*1024):
        require(os.name=='nt','FILE_PLATFORM_UNSUPPORTED')
        root=PureWindowsPath(os.path.abspath(root))
        require(len(root.drive)==2 and root.drive[1]==':' and root.is_absolute(),'FILE_ROOT_DENIED')
        filesystem=ctypes.create_unicode_buffer(32)
        require(kernel.GetDriveTypeW(root.anchor)==3 and kernel.GetVolumeInformationW(root.anchor,None,0,None,None,None,filesystem,len(filesystem))
                and filesystem.value.casefold()=='ntfs','FILE_PLATFORM_UNSUPPORTED')
        require(type(max_bytes) is int and 0<max_bytes<=64*1024*1024,'FILE_LIMIT')
        self.root=root;self.max_bytes=max_bytes

    @staticmethod
    def _components(name):
        safe_name(name)
        reserved={'CON','PRN','AUX','NUL',*(f'COM{i}' for i in range(1,10)),*(f'LPT{i}' for i in range(1,10))}
        parts=name.split('/')
        require(all(not any(ord(c)<32 for c in p) and p.split('.')[0].upper() not in reserved for p in parts),'FILE_NAME_DENIED')
        return parts

    @staticmethod
    def _info(handle):
        info=Info();require(kernel.GetFileInformationByHandle(handle,ctypes.byref(info)),'FILE_METADATA_DENIED')
        require(not info.attributes & 0x400,'FILE_REPARSE_DENIED')
        require(kernel.GetFileType(handle)==1,'FILE_TYPE_DENIED')
        return info

    @classmethod
    @contextmanager
    def _open(cls,path,*,directory,parent=None):
        # FILE_SHARE_READ only: deny concurrent writes, rename, replacement or deletion.
        # Type-neutral native open: no undocumented combination of DIRECTORY_FILE
        # and OPEN_REPARSE_POINT. Metadata below verifies the actual object type.
        object_name=('\\??\\'+str(path)) if parent is None else path.name
        text=ctypes.create_unicode_buffer(object_name)
        name=UnicodeString(len(object_name.encode('utf-16-le')),len(text)*2,ctypes.cast(text,w.LPWSTR))
        attrs=ObjectAttributes(ctypes.sizeof(ObjectAttributes),parent,ctypes.pointer(name),0x40,None,None)
        handle=w.HANDLE();status=IOStatus()
        result=native.NtCreateFile(ctypes.byref(handle),0x100000 | 0x80 | (0x20 if directory else 1),
            ctypes.byref(attrs),ctypes.byref(status),None,0,1,1,0x00200000 | 0x20,None,0)
        if result!=0:
            if handle.value not in (None,ctypes.c_void_p(-1).value):kernel.CloseHandle(handle.value)
            raise Denied('FILE_OPEN_DENIED')
        handle=handle.value
        require(handle not in (None,ctypes.c_void_p(-1).value),'FILE_OPEN_DENIED')
        try:
            info=cls._info(handle)
            require(bool(info.attributes & 0x10)==directory,'FILE_TYPE_DENIED')
            buf=ctypes.create_unicode_buffer(32768)
            size=kernel.GetFinalPathNameByHandleW(handle,buf,len(buf),0)
            require(0<size<len(buf) and buf.value.casefold()==('\\\\?\\'+str(path)).casefold(),'FILE_PATH_DENIED')
            yield handle,info
        finally: kernel.CloseHandle(handle)

    def read_bytes(self,name):
        parts=self._components(name)
        try:
            with ExitStack() as stack:
                # Pin the selected root once; descend using NT RootDirectory handles.
                # Renaming/replacing any ancestor outside root cannot redirect these opens.
                path=self.root
                parent,_=stack.enter_context(self._open(path,directory=True))
                for part in parts[:-1]:
                    path=path/part
                    parent,_=stack.enter_context(self._open(path,directory=True,parent=parent))
                handle,info=stack.enter_context(self._open(path/parts[-1],directory=False,parent=parent))
                require(info.links==1,'FILE_HARDLINK_DENIED')
                size=(info.size_high<<32)|info.size_low;require(size<=self.max_bytes,'FILE_TOO_LARGE')
                data=bytearray()
                while len(data)<size:
                    chunk=ctypes.create_string_buffer(min(65536,size-len(data)));count=w.DWORD()
                    require(kernel.ReadFile(handle,chunk,len(chunk),ctypes.byref(count),None) and count.value>0,'FILE_READ_DENIED')
                    data.extend(chunk.raw[:count.value])
                after=self._info(handle)
                require(after.links==1 and after.size_high==info.size_high and after.size_low==info.size_low
                        and after.index_high==info.index_high and after.index_low==info.index_low,'FILE_CHANGED')
                return bytes(data)
        except Denied: raise
        except (OSError,ValueError,TypeError): raise Denied('FILE_READ_DENIED') from None
