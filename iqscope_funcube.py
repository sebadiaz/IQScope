"""Partial FUNcube-1 FM interpretation; profile match is not sender identity."""
SPEC_URL='https://funcube.org.uk/wp-content/uploads/2010/11/funcube-1-downlink-data-spec_ver1-as_flown.pdf'
EQUATIONS_URL='https://funcube.org.uk/wp-content/uploads/2010/11/funcube-1_-telemetry_equations_b1.xls'
UNITS_URL='https://amsat-nl.org/status/'


def interpret_funcube(payload):
    result={'schema_version':'0.1','parser':'funcube_fc1_realtime_partial','identity_confirmed':False,
            'validation':'candidate profile interpretation; no independent sensor calibration or sender identity verification',
            'sources':[SPEC_URL,EQUATIONS_URL,UNITS_URL]}
    if len(payload)!=256:
        return dict(result,status='invalid_length',expected_bytes=256,actual_bytes=len(payload))
    packet=bytes(payload)
    model=packet[0]>>6
    code=packet[0]&63
    result['header']={'raw_byte':packet[0],'satellite_id':model,'frame_type_code':code}
    # Only the flight model profile is supported; other model calibrations differ.
    if model!=2 or code>24:
        return dict(result,status='unsupported_profile')
    integer=int.from_bytes(packet,'big')
    def read(offset,width):
        return (integer>>(2048-offset-width))&((1<<width)-1)
    validity_names=('asib','eps','pa','rf','mse','ants_bus_b','ants_bus_a')
    validity={name:bool(read(436+i,1)) for i,name in enumerate(validity_names)}
    modes={name:bool(read(443+i,1)) for i,name in enumerate(('eclipse','safe_mode','hardware_abf','software_abf','deployment_wait'))}
    fields=[]
    names=(('panel_voltage_1','Tension panneau 1','mV'),('panel_voltage_2','Tension panneau 2','mV'),
           ('panel_voltage_3','Tension panneau 3','mV'),('total_photo_current','Courant photovoltaïque','mA'),
           ('battery_voltage','Tension batterie','mV'),('system_current','Courant système','mA'),
           ('reboot_count','Redémarrages EPS','count'),('software_error_count','Erreurs logicielles EPS','count'))
    for index,(name,label,unit) in enumerate(names):
        offset=8+index*16
        value=read(offset,16)
        fields.append({'id':name,'label':label,'raw_value':value,'value':value,'unit':unit,
                       'bit_offset':offset,'bit_width':16,'source_valid':validity['eps'],
                       'conversion':'direct transmitted value'})
    raw_names=('boost_temperature_1','boost_temperature_2','boost_temperature_3','battery_temperature',
               'latchup_count_5v','latchup_count_3v3','reset_cause','power_point_tracking_mode')
    raw_fields=[{'id':name,'raw_value':read(136+i*8,8),'unit':None,
                 'bit_offset':136+i*8,'bit_width':8,'source_valid':validity['eps']}
                for i,name in enumerate(raw_names)]
    return dict(result,status='candidate_interpretation',profile='FUNcube-1 Flight Model',
                sequence_number=read(400,24),source_validity=validity,modes=modes,
                measurements=fields,raw_fields=raw_fields,
                uninterpreted_sections=[{'byte_offset':25,'byte_length':25,'hex':packet[25:50].hex()},
                                        {'byte_offset':56,'byte_length':200,'hex':packet[56:].hex()}],
                limitations=['Partial FC1 flight-model profile only; a matching header does not uniquely identify a protocol or emitter.',
                             'EPS validity is declared by the packet, not independently measured; invalid blocks may contain stale readings.',
                             'Temperature codes, ASIB/RF/PA calibration and orbit/high-resolution/message payloads are not interpreted.',
                             'Raw frame-type code retained: published schedule and decoder implementations differ in slot numbering.'])
