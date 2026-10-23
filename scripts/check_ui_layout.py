import sys,json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from dji_graft_gui import App,_enable_dpi_awareness
_enable_dpi_awareness()
a=App();a.update()
assert a.acceleration.get()=='自动选择 · 显卡优先'
assert a.max_bitrate.get()=='2000'
assert '5.0' in a.title()
results=[]
for w,h in [(1080,700),(920,630),(1280,760)]:
    a.geometry(f'{w}x{h}');a.update()
    for mode in ('single','batch'):
        a.mode.set(mode);a._on_mode_change();a.update()
        for name in ('start_btn','open_btn','ref_entry','input_entry','output_entry','acceleration_box','crf_entry','bitrate_entry','encoder_hint','install_btn','copy_btn','save_btn','log_text'):
            widget=getattr(a,name)
            x=widget.winfo_rootx()-a.winfo_rootx();y=widget.winfo_rooty()-a.winfo_rooty()
            box=[x,y,widget.winfo_width(),widget.winfo_height()]
            assert widget.winfo_ismapped() and x>=0 and y>=0 and x+box[2]<=a.winfo_width() and y+box[3]<=a.winfo_height(),(w,h,mode,name,box)
            parent=widget.master
            while parent is not None:
                assert widget.winfo_rootx()>=parent.winfo_rootx() and widget.winfo_rooty()>=parent.winfo_rooty() and widget.winfo_rootx()+widget.winfo_width()<=parent.winfo_rootx()+parent.winfo_width() and widget.winfo_rooty()+widget.winfo_height()<=parent.winfo_rooty()+parent.winfo_height(),(w,h,mode,name,'clipped by',str(parent))
                parent=parent.master
        results.append([w,h,mode,'all controls visible'])
a.mode.set('single');a._on_mode_change();a.input_path.set('single.mp4');a.output_path.set('single-out.mp4')
a.mode.set('batch');a._on_mode_change();a.input_path.set('batch-dir');a.output_path.set('batch-out')
a.mode.set('single');a._on_mode_change();assert a.input_path.get()=='single.mp4'
a._set_running(True);assert all(str(x.cget('state'))=='disabled' for x in a._controls)
a._set_running(False);assert str(a.acceleration_box.cget('state'))=='readonly'
print(json.dumps(results));a.destroy()
