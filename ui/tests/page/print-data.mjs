// The print dialog's boot data for the page scenarios and the screenshots (plugin.ask_print builds the real one).
export const PRINT_DATA = {
  printer: {name: 'Bench Kobra', host: '192.168.1.50', state: 'idle', can_print: true, model: 'Anycubic Kobra X'},
  job: {name: 'Benchy dual colour', plate: 1, seconds: 7380, grams: 42.5, metres: 14.18, thumbnail: ''},
  filaments: [{index: 0, colour: '#E5484D', type: 'PLA', family: 'PLA', material: 'PLA', grams: 30.2}, {index: 2, colour: '#3E63DD', type: 'PETG', family: 'PETG', material: 'PETG', grams: 12.3}],
  slots: [
    {tray: 4, global_index: 0, box_id: 0, index: 0, type: 'PLA', family: 'PLA', material: 'PLA', colour: '#E5484D', usable: true, spool: 'Elegoo Red PLA'},
    {tray: 5, global_index: 1, box_id: 0, index: 1, type: 'PETG', family: 'PETG', material: 'PETG', colour: '#3E63DD', usable: true, spool: ''},
    {tray: 6, global_index: 2, box_id: 0, index: 2, type: '', family: '', material: '', colour: '#FFFFFF', usable: false, spool: ''},
    {tray: 7, global_index: 3, box_id: 0, index: 3, type: 'PLA SILK', family: 'PLA', material: 'PLA SILK', colour: '#FFFFFF', usable: true, spool: 'Sunlu White'}],
  trays: {'0': 4, '2': 5},
  options: [{key: 'auto_leveling', on: true, lock: ''}, {key: 'vibration_compensation', on: true, lock: ''},
    {key: 'flow_calibration', on: false, lock: 'setting'}, {key: 'timelapse', on: false, lock: 'unsupported'}],
  auto_feed: true, remember: true,
};
