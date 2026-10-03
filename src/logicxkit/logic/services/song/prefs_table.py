"""The settings `prefs.py` knows: the Settings window's name for each, the key it lives under
in `com.apple.logic10`, and how the value is stored. Every row was pinned by changing that one
control, closing the window and diffing the preferences (Logic 12.3.1; General > Editing on
2026-09-05, the rest on 2026-09-08). Not here because the window flushed nothing for them:
Audio > Devices (untouched), Software monitoring, Plug-in Delay Compensation (asks first),
MIDI > Sync's two "All" boxes, every Control Surfaces box (they live in
`com.apple.logic.pro.cs`, Logic's own file), and the sliders that would not move.
`CrossfadeSettings.LeftTime` / `.LeftCurve` (Audio > Editing) change with the crossfade
sliders but carry a derived `.TotalSamples` beside them, so they are left to Logic."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Setting:
    name: str                 # as the Settings window labels it
    key: str                  # the plist key
    pane: str                 # Settings window pane
    kind: str = "bool"        # bool | int | float | str | choice | bit (a flag in an int) | databit (a flag in a data blob)
    inverted: bool = False    # the key stores the box unticked (Logic's "_n" and "Disabled" keys)
    choices: tuple[str, ...] = ()   # for kind "choice": the popup's items
    values: tuple = ()        # for kind "choice": what each item stores, when not its index (None = key absent)
    mask: int = 0             # for bit and databit: the flag
    offset: int = 0           # for databit: which byte of the blob
    width: int = 0            # for bit: the int is this many bits, sign-extended (8 for a byte)

    def stored(self, choice: str):
        i = self.choices.index(choice)
        return self.values[i] if self.values else i

    def choice_of(self, raw):
        """The item a stored value names, or ``choice N`` for one the table lacks."""
        if self.values:
            for item, v in zip(self.choices, self.values, strict=True):
                if _same(v, raw):
                    return item
            return f"choice {raw}"
        n = int(raw)
        return self.choices[n] if 0 <= n < len(self.choices) else f"choice {n}"


def _same(stored, raw) -> bool:
    """Whether ``raw`` (as `defaults read` prints it) is the table's ``stored`` value."""
    text = str(raw).strip()
    if stored is None:
        return raw is None
    if isinstance(stored, bool):
        return (text.lower() in ("1", "true", "yes")) == stored
    if isinstance(stored, (int, float)):
        try:
            return float(text) == float(stored)
        except ValueError:
            return False
    return text == str(stored)


_PH, _EDITING, _CYCLE, _CATCH, _ACC = ("General > Project Handling", "General > Editing", "General > Cycle",
                                       "General > Catch", "General > Accessibility")
_AUDIO, _SAMPLER, _AEDIT, _FILE = "Audio > General", "Audio > Sampler", "Audio > Editing", "Audio > File Editor"
_REC, _MIDI, _RESET, _SYNC = "Recording", "MIDI > General", "MIDI > Reset Messages", "MIDI > Sync"
_SCORE, _MOVIE, _AUTO = "Score", "Movie", "Automation"
_VIEW, _TRACKS, _MIXER, _EDITORS, _INFO = "View > General", "View > Tracks", "View > Mixer", "View > Editors", "My Info"
_PER_STRIP = ("Per Channel Strip", "Global")
_TAKE_MIDI_OFF = ("Create Take Folder", "Merge", "Overlap", "Overlap/Merge Selected Regions", "Create Track",
                  "Create Track Alternative")
_TAKE_MIDI_ON = ("Create Take Folder", "Merge", "Merge Current Recording Only", "Create Tracks",
                 "Create Tracks and Mute", "Create Track Alternatives")
_TIME_AS = ("Hours : Minutes : Seconds . Milliseconds", "Hours : Minutes : Seconds . Samples", "SMPTE/EBU with Subframes",
            "SMPTE/EBU Without Subframes", "SMPTE/EBU with Quarter Frames", "SMPTE/EBU with Samples",
            "Feet and Frames, 35 mm Film", "Feet and Frames, 16 mm Film")
_RETURN = ("Very Slow (4 dB/s)", "EBU Slow (6.3 dB/s)", "IEC Type II/EBU Normal (8.6 dB/s)",
           "IEC Type I (11.8 dB/s)—Recommended", "Fast (20 dB/s)", "Faster (30 dB/s)", "Very Fast (50 dB/s)")

SETTINGS: tuple[Setting, ...] = (
    Setting("Export MIDI File command saves single MIDI region as format 0", "SaveSMFInFormat0_n", _PH, inverted=True),
    Setting("Save undo history with project", "SaveUndoHistoryWithSong", _PH),
    Setting("Auto Backup", "MaxAutoBackups", _PH, "choice",
            choices=("Off", "Last Alternative Version", "Last 3 Alternative Versions", "Last 10 Alternative Versions",
                     "Last 30 Alternative Versions", "Last 50 Alternative Versions", "Last 100 Alternative Versions"),
            values=(0, 1, 3, 10, 30, 50, 100)),
    Setting("Recent Items", "NSRecentDocumentsLimit", _PH, "choice",
            choices=("System Default", "None", "5", "10", "15", "20", "30", "40", "50"),
            values=(None, 0, 5, 10, 15, 20, 30, 40, 50)),
    Setting("Close the current project when opening another", "AlwaysCloseDocumentWhenOpeningAnotherOne_n", _PH,
            inverted=True),
    Setting("Ask before closing the current project", "AskToCloseDocument_n", _PH, inverted=True),
    Setting("Number of undo steps", "UndoSteps", _EDITING, "int"),
    Setting("Groove template edits immediately update all associated regions", "LiveGroove_n", _EDITING, inverted=True),
    Setting("Create new regions after splitting loops", "SmartLoopDisabled", _EDITING, inverted=True),
    Setting("Advanced split and marquee handling of MIDI regions", "AdvancedSplitHandling", _EDITING),
    Setting("Select regions on track selection", "SelectRegionsOnTrackSelection_n", _EDITING, inverted=True),
    Setting("Select tracks on region/marquee selection", "SelectTrackOnRegionSelection", _EDITING),
    Setting("Right mouse button", "RightButtonFunction", _EDITING, "choice",
            choices=("Is Assignable to a Tool", "Opens Tool Menu", "Opens Shortcut Menu", "Opens Tool and Shortcut Menu")),
    Setting("Enable Force Touch trackpad", "SupportForceTouchTrackpad", _EDITING),
    Setting("Fade tool click zones", "FadeToolClickZones", _EDITING),
    Setting("Marquee tool click zones", "MarqueeToolClickZones", _EDITING),
    Setting("Quick Swipe and Take Editing click zones", "TakeClickZones", _EDITING),
    Setting("Limit dragging to one direction in Piano Roll and Score", "LimitDraggingToOneDirection", _EDITING),
    Setting("Limit dragging to one direction in Tracks area", "LimitDraggingToOneDirectionArrange", _EDITING),
    Setting("Double-clicking a MIDI region opens", "DefaultMIDIEditor", _EDITING, "choice",
            choices=("Score Editor", "Event List", "Piano Roll Editor")),
    Setting("Piano Roll region border trimming", "LockPianoRollRegionBorders", _EDITING, inverted=True),
    Setting("Cycle Pre-Processing", "CycleBetrug", _CYCLE, "choice", choices=("1/96", "1/192", "4 Ticks", "Off")),
    Setting("Smooth Cycle Algorithm", "SmoothCycle", _CYCLE),
    Setting("Catch when starting playback", "EnableCatchWhenStartingPlayback_n", _CATCH, inverted=True),
    Setting("Catch when moving playhead", "EnableCatchWhenMovingPlayhead_n", _CATCH, inverted=True),
    Setting("Catch content by position if Catch and Link are enabled", "AllowContentCatch_n", _CATCH, inverted=True),
    Setting("Open Plug-in windows in Controls view by default", "OpenPlugInsInControlsView", _ACC),
    Setting("Announce playhead position when playing", "AnnouncePlayheadPlaying", _ACC, inverted=True),
    Setting("Announce playhead position when recording", "AnnouncePlayheadRecording", _ACC),
    Setting("Announce playhead position when scrubbing", "AnnouncePlayheadScrubbing", _ACC, inverted=True),
    Setting("Display audio engine overload message", "DisplayOverloadMessage_n", _AUDIO, inverted=True),
    Setting("Low Latency Monitoring Mode", "LowLatencyMode", _AUDIO),
    Setting("Playback pre-roll", "PlaybackPreRoll", _AUDIO),
    Setting("Sample Accurate Automation", "SampleAccurateAuto", _AUDIO, "choice",
            choices=("Off", "Volume, Pan, Sends", "Volume, Pan, Sends, Plug-in Parameters"), values=(-1, 0, 1)),
    Setting("Automatic Bus Assignment Uses", "AutomaticBusAssignmentStart", _AUDIO, "choice",
            choices=("All Busses", "Busses Above 8", "Busses Above 16", "Busses Above 24", "Busses Above 32",
                     "Busses Above 64", "Busses Above 96", "Busses Above 128"), values=(0, 8, 16, 24, 32, 64, 96, 128)),
    Setting("Dim level (dB)", "DimLevel", _AUDIO, "float"),
    Setting("Keep common samples in memory when switching projects", "SamplerReserveRefCount", _SAMPLER),
    Setting("Sample Storage", "SamplerUnPackAudioData", _SAMPLER, "choice", choices=("Original", "32-bit float"),
            values=(False, True)),
    Setting("Search Samples On", "SamplerSearchOptions", _SAMPLER, "choice",
            choices=("Local Volumes", "External Volumes", "All Volumes")),
    Setting("Read Root Key From", "SamplerReadKeyNoteFrom", _SAMPLER, "choice",
            choices=("File/Analysis", "Filename/Analysis", "Filename Only", "File Only", "Analysis Only")),
    Setting("Root Key at File Name Position", "SamplerReadKeyNoteAtPos", _SAMPLER, "choice",
            choices=("Auto",) + tuple(str(n) for n in range(1, 31))),
    Setting("Scrubbing with audio in Tracks area", "ScrubAudioInArrange", _AEDIT),
    Setting("Maximum Scrub Speed", "ScrubSpeed", _AEDIT, "choice", choices=("Normal", "Double")),
    Setting("Scrub Response", "ScrubResponse", _AEDIT, "choice", choices=("Slow", "Normal", "Fast", "Faster"),
            values=(1, 2, 3, 4)),
    Setting("Warning before processing function by key command", "WarnBeforeProcessingByKeyCommand_n", _FILE,
            inverted=True),
    Setting("Clear Undo History when closing project", "SampleEditorClearUndoAfterQuit", _FILE),
    Setting("Record selection changes in Undo History", "SampleEditorRecordSelectionChangesInUndo", _FILE),
    Setting("Record Normalize operations in Undo History", "RecordNormalizeOperationsInUndoHistory_n", _FILE,
            inverted=True),
    Setting("File Editor undo steps", "SampleEditorUndoSteps", _FILE, "int"),
    Setting("File Type", "RecordingFileType", _REC, "choice", choices=("AIFF", "WAVE (BWF)", "CAF"), values=(1, 2, 3)),
    Setting("Auto Record Enable", "AutoRecEnableAllSelectedMIDITracks", _REC, "choice",
            choices=("The Focused Track", "All Selected Tracks"), values=(False, True)),
    Setting("Overlapping MIDI recordings, cycle off", "RecOptMidiNoCycle", _REC, "choice", choices=_TAKE_MIDI_OFF,
            values=(1, 2, 7, 3, 4, 9)),
    Setting("Overlapping audio recordings, cycle off", "RecOptAudioNoCycle", _REC, "choice",
            choices=("Create Take Folder", "Create New Track", "Create Track Alternative"), values=(1, 4, 9)),
    Setting("Overlapping MIDI recordings, cycle on", "RecOptMidiCycle", _REC, "choice", choices=_TAKE_MIDI_ON,
            values=(1, 2, 8, 4, 5, 9)),
    Setting("Overlapping audio recordings, cycle on", "RecOptAudioCycle", _REC, "choice",
            choices=("Create Take Folder", "Create Tracks and Mute", "Create Track Alternatives"), values=(1, 5, 9)),
    Setting("Overlapping MIDI recordings, replace", "RecOptMidiReplace", _REC, "choice",
            choices=("Region Erase", "Region Punch", "Content Erase", "Content Punch"), values=(0, 2, 1, 3)),
    Setting("External stop message ends recording", "StopEndsRecording_n", _MIDI, inverted=True),
    Setting("Articulation switching", "ArticulationSwitchingEnabledGlobal", _MIDI, "choice", choices=_PER_STRIP,
            values=(False, True)),
    Setting("Articulation input MIDI channel", "ArticulationInputMidiChannelGlobal", _MIDI, "choice",
            choices=_PER_STRIP, values=(False, True)),
    Setting("Articulation octave offset", "ArticulationOctaveOffsetGlobal", _MIDI, "choice", choices=_PER_STRIP,
            values=(False, True)),
    Setting("Control 64 (Sustain) off, software instruments", "MIDIResetSISendSustainReset", _RESET),
    Setting("Control 4 (Foot Control) to zero, software instruments", "MIDIResetSISendFootReset", _RESET),
    Setting("Control 2 (Breath) to zero, software instruments", "MIDIResetSISendBreathReset", _RESET),
    Setting("Control 1 (Modulation) to zero, software instruments", "MIDIResetSISendModWheelReset", _RESET),
    Setting("Aftertouch to zero, software instruments", "MIDIResetSISendPressureReset", _RESET),
    Setting("Pitch Bend to center position, software instruments", "MIDIResetSISendPitchBendReset", _RESET),
    Setting("Control 123 (All Notes Off), external instruments", "MIDIResetExternalInstruments", _RESET, "bit",
            mask=0x01, width=8),
    Setting("Control 121 (Reset Controls), external instruments", "MIDIResetExternalInstruments", _RESET, "bit",
            mask=0x02, width=8),
    Setting("Control 64 (Sustain) off, external instruments", "MIDIResetExternalInstruments", _RESET, "bit",
            mask=0x04, width=8),
    Setting("Control 4 (Foot Control) to zero, external instruments", "MIDIResetExternalInstruments", _RESET, "bit",
            mask=0x08, width=8),
    Setting("Control 2 (Breath Control) to zero, external instruments", "MIDIResetExternalInstruments", _RESET,
            "bit", mask=0x10, width=8),
    Setting("Control 1 (Modulation) to zero, external instruments", "MIDIResetExternalInstruments", _RESET, "bit",
            mask=0x20, width=8),
    Setting("Aftertouch to zero, external instruments", "MIDIResetExternalInstruments", _RESET, "bit", mask=0x40,
            width=8),
    Setting("Pitch Bend to center position, external instruments", "MIDIResetExternalInstruments", _RESET, "bit",
            mask=0x80, width=8),
    Setting("Send used instrument settings on reset", "MIDIUseUsedInstrumentOnReset", _RESET),
    Setting("MMC Uses", "FostexType", _SYNC, "choice", choices=("MMC Standard Messages", "Old Fostex Format"),
            values=(1, 0)),
    Setting("Transmit locate commands when pressing Stop twice", "TransmitLocateCmdOnDoubleStop", _SYNC),
    Setting("Transmit locate commands when dragging regions or events", "TransmitLocateCmdOnDraggingRegions", _SYNC),
    Setting("Transmit record-enable commands for audio tracks", "TransmitLocateCmdOnRecordEnable", _SYNC),
    Setting("Global MIDI delay (microseconds)", "GlobalMIDIDelay", _SYNC, "int"),
    Setting("MMC pickup delay", "PickupDelay", _SYNC, "int"),
    Setting("MTC send offset", "MTCSendOffset", _SYNC, "int"),
    Setting("Auto split notes in polyphonic staff styles", "ScoreAutoSplitEnabled", _SCORE),
    Setting("Show region selection in color", "ScoreHideStaveSel", _SCORE, inverted=True),
    Setting("Display distance values in inches", "ScoreInch", _SCORE),
    Setting("Double-Click to Open", "ScoreNoteClickOpen", _SCORE, "choice",
            choices=("Note Attributes", "Event List", "Piano Roll Editor", "Step Editor")),
    Setting("Camera tool output", "ScorePictMode", _SCORE, "choice", choices=("Clipboard", "PDF file")),
    Setting("Use Logic Pro audio output", "VideoMovieAudioUsesLogicAudioDevice", _MOVIE),
    Setting("Lock movie window when changing screensets", "VideoWindowIsNotInScreenset", _MOVIE),
    Setting("Cache Resolution", "VideoThumbnailCacheResolution", _MOVIE, "choice", choices=("Low", "Medium", "High", "Best")),
    Setting("Movie to project adjust (raw, 16 per frame)", "VideoToSongAdjust", _MOVIE, "int"),
    Setting("Thumbnail cache size (MB)", "VideoThumbnailCacheSize", _MOVIE, "int"),
    Setting("Move Track Automation with Regions", "Automation.MoveMode", _AUTO, "choice", choices=("Never", "Always", "Ask")),
    Setting("Include trails, if possible", "Automation.IncludeTrails", _AUTO),
    Setting("Create Node when cutting at constant values", "Automation.AlwaysCreateStartAutomationNodeInSplitRegion", _AUTO),
    Setting("Pencil Tool", "Automation.PencilSteppedEditing", _AUTO, "choice",
            choices=("Hold Option for Stepped Editing", "Hold Option for Curved Editing"), values=(True, False)),
    Setting("Snap offset (ticks)", "Automation.SnapOffsets", _AUTO, "int"),
    Setting("Ramp time (ms)", "Automation.NormalRamp", _AUTO, "int"),
    Setting("Write Mode Changes To", "Automation.WriteFallback", _AUTO, "choice",
            choices=("Off", "Read", "Touch", "Latch", "Write")),
    Setting("Write: Volume", "Automation.WriteBits", _AUTO, "databit", mask=0x01, offset=1),
    Setting("Write: Pan", "Automation.WriteBits", _AUTO, "databit", mask=0x02, offset=1),
    Setting("Write: Mute", "Automation.WriteBits", _AUTO, "databit", mask=0x04, offset=1),
    Setting("Write: Send", "Automation.WriteBits", _AUTO, "databit", mask=0x08, offset=1),
    Setting("Write: Plug-in", "Automation.WriteBits", _AUTO, "databit", mask=0x10, offset=1),
    Setting("Write: Solo", "Automation.WriteBits", _AUTO, "databit", mask=0x20, offset=1),
    Setting("Display Middle C As", "MiddleC", _VIEW, "choice", choices=("C4 (Roland)", "C3 (Yamaha)"), values=(True, False)),
    Setting("Display Time As", "SMPTEDisplayMode", _VIEW, "choice", choices=_TIME_AS, values=(5, 6, 0, 1, 2, 7, 3, 4)),
    Setting("Zeros as spaces", "DisplaySMPTEZerosAsSpaces", _VIEW),
    Setting("Display Tempo As", "TempoDisplayMode", _VIEW, "choice",
            choices=("Beats per Minute (BPM, Maelzel)", "BPM Without Decimals", "Frames per Click with Eighths",
                     "Frames per Click with Decimals")),
    Setting("Clock Format", "ClockDisplay", _VIEW, "choice",
            choices=("1  1  1  1", "1. 1. 1. 1", "1  1  1  0", "1. 1. 1. 0", "1  1    1", "1. 1.   1", "1  1    0", "1. 1.   0")),
    Setting("Display MIDI Data As", "MIDI2DisplayMode", _VIEW, "choice", choices=("MIDI 1.0", "0.0 - 127.9", "Percent"),
            values=(1, 2, 3)),
    Setting("Large local window menus", "LargeMenu", _VIEW),
    Setting("Large inspectors", "LargeInspector", _VIEW),
    Setting("Wide playhead", "WideSPL_n", _VIEW, inverted=True),
    Setting("Show help tags", "HideHelpTags", _VIEW, inverted=True),
    Setting("Show beats and time in help tags", "HelpTagsShowBoth", _VIEW),
    Setting("Show default values", "HideDefaultValue", _VIEW, inverted=True),
    Setting("Show animations", "ShowAnimations", _VIEW),
    Setting("Appearance", "Appearance", _VIEW, "choice", choices=("Light", "Dark", "System Setting"), values=(1, 2, 0)),
    Setting("Show track or bar number while scrolling", "ShowTrackOrBarNumberWhileScrolling", _TRACKS),
    Setting("Track color auto-assign, 24 colors", "AutoColorCST24", _TRACKS),
    Setting("Track color auto-assign, 96 colors", "AutoColorCST96", _TRACKS),
    Setting("Region Color", "IndividualRegionColors_n", _TRACKS, "choice", choices=("As Track Color", "Individual"),
            values=(True, False)),
    Setting("Marker color auto-assign, 24 colors", "AutoColorMarker24", _TRACKS),
    Setting("Marker color auto-assign, 96 colors", "AutoColorMarker96", _TRACKS),
    Setting("Background", "TracksBackgroundMode", _TRACKS, "choice", choices=("Dark", "Bright", "Custom")),
    Setting("Grid", "GridAboveRegions", _TRACKS, "choice", choices=("Background", "Foreground"), values=(False, True)),
    Setting("Grid: automatic", "TracksGridAutomatic", _TRACKS),
    Setting("Shaded loops", "AlternateLoopsDisplay", _TRACKS),
    Setting("Show “+” button next to Session Player regions", "ShowDrummerPlusButtons", _TRACKS, inverted=True),
    Setting("Peak Hold Time", "LevelMeterPeakHoldDuration", _MIXER, "choice", choices=("800 ms", "2 s", "4 s", "Infinite"),
            values=(0.800000011920929, 2.0, 4.0, -1.0)),
    Setting("Return Time", "LevelMeterReturnSpeed", _MIXER, "choice", choices=_RETURN,
            values=(-4.0, -6.300000190734863, -8.600000381469727, -11.800000190734863, -20.0, -30.0, -50.0)),
    Setting("Channel Order", "LevelMeterOrder", _MIXER, "choice",
            choices=("DTS (L R Ls Rs C LFE)", "SMPTE/ITU (L R C LFE Ls Rs)", "Clockwise (Ls L C R Rs LFE)", "Film (L C R Ls Rs LFE)")),
    Setting("Open plug-in window on insertion", "AutoOpenPluginUI_n", _MIXER, inverted=True),
    Setting("Recent plug-ins shown in the plug-in menu (0 hides the list)", "MostRecentPluginsToShow", _MIXER, "int"),
    Setting("Show “Mastering Assistant” Button in Stereo Output",
            "HideMasteringAssistantButtonInStereoOutputChannelStrip", _MIXER, inverted=True),
    Setting("Bright background", "PianoRollColor", _EDITORS),
    Setting("Composer", "MyInfoComposerName", _INFO, "str"),
    Setting("Artist", "MyInfoArtistName", _INFO, "str"),
    Setting("Album", "MyInfoAlbumName", _INFO, "str"),
    Setting("Playlist", "MyInfoITunesPlaylist", _INFO, "str"),
)
BY_NAME = {s.name: s for s in SETTINGS}
BY_KEY = {s.key: s for s in SETTINGS if s.kind not in ("bit", "databit")}
