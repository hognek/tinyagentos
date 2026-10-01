### Fixed

- Lock-screen USB tile: the read-back poll after a switch now gives up 12s after it starts, even if the mode helper hangs during the poll (a hung helper could hold it for minutes). The 12s covers only that poll: the first read of the current mode and the switch itself run before it starts. A failing mode list no longer throws away the mode already read.
