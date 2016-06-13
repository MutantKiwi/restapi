# look for arcpy access, otherwise use open source version
# open source version may be faster?
from __future__ import print_function
try:
    import imp
    imp.find_module('arcpy')
    from arc_restapi import *
    __opensource__ = False

except ImportError:
    from open_restapi import *
    __opensource__ = True

from rest_utils import *
from . import _strings
from  .decorator import decorator

__all__ = ['MapServiceLayer',  'ImageService', 'Geocoder', 'FeatureService', 'FeatureLayer', '__opensource__',
           'exportFeatureSet', 'exportReplica', 'exportFeaturesWithAttachments', 'Geometry', 'GeometryCollection',
           'GeocodeService', 'GPService', 'GPTask', 'POST', 'MapService', 'ArcServer', 'Cursor', 'FeatureSet',
           'generate_token', 'mil_to_date', 'date_to_mil', 'guessWKID', 'validate_name', 'exportGeometryCollection',
           'GeometryService', 'GeometryCollection'] + [d for d in dir(_strings) if not d.startswith('__')]

@decorator
def geometry_passthrough(func, *args, **kwargs):
    """decorator to return a single geometry if a single geometry was returned
    in a GeometryCollection(), otherwise returns the full GeometryCollection()
    """
    f = func(*args, **kwargs)
    gc = GeometryCollection(f)
    if gc.count == 1:
        return gc[0]
    else:
        return gc
    return f

def exportGeometryCollection(gc, output):
    """Exports a goemetry collection to shapefile or feature class

    Required:
        gc -- GeometryCollection() object
        output -- output data set (will be geometry only)
    """
    if isinstance(gc, Geometry):
        gc = GeometryCollection(gc)
    if not isinstance(gc, GeometryCollection):
        raise ValueError('Input is not a GeometryCollection!')

    fs_dict = {}
    fs_dict[SPATIAL_REFERENCE] = {WKID: gc.spatialReference}
    fs_dict[GEOMETRY_TYPE] = gc.geometryType
    fs_dict[DISPLAY_FIELD_NAME] = ''
    fs_dict[FIELD_ALIASES] = {OBJECTID: OBJECTID}
    fs_dict[FIELDS] = [{NAME: OBJECTID,
                        TYPE: OID,
                        ALIAS: OBJECTID}]
    fs_dict[FEATURES] = [{ATTRIBUTES: {OBJECTID:i+1}, GEOMETRY:ft.json} for i,ft in enumerate(gc)]

    fs = FeatureSet(fs_dict)
    return exportFeatureSet(fs, output)

class Cursor(FeatureSet):
    """Class to handle Cursor object"""
    json = {}
    fieldOrder = []
    field_names = []

    def __init__(self, feature_set, fieldOrder=[]):
        """Cursor object for a feature set
        Required:
            feature_set -- feature set as json or restapi.FeatureSet() object
        Optional:
            fieldOrder -- order of fields for cursor row returns.  To explicitly
                specify and OBJECTID field or Shape (geometry field), you must use
                the field tokens 'OID@' and 'SHAPE@' respectively.
        """
        if isinstance(feature_set, FeatureSet):
            feature_set = feature_set.json

        super(Cursor, self).__init__(feature_set)
        self.fieldOrder = self.__validateOrderBy(fieldOrder)

    @property
    def date_fields(self):
        """gets the names of any date fields within feature set"""
        return [f.name for f in self.fields if f.type == DATE_FIELD]

    @property
    def field_names(self):
        """gets the field names for feature set"""
        names = []
        for f in self.fieldOrder:
            if f == OID_TOKEN and self.OIDFieldName:
                names.append(self.OIDFieldName)
            elif f == SHAPE_TOKEN and self.ShapeFieldName:
                names.append(self.ShapeFieldName)
            else:
                names.append(f)
        return names

    @property
    def OIDFieldName(self):
        """gets the OID field name if it exists in feature set"""
        try:
            return [f.name for f in self.fields if f.type == OID][0]
        except IndexError:
           return None

    @property
    def ShapeFieldName(self):
        """gets the Shape field name if it exists in feature set"""
        try:
            return [f.name for f in self.fields if f.type == SHAPE][0]
        except IndexError:
           return None

    def get_rows(self):
        """returns row objects"""
        for feature in self.features:
            yield self.__createRow(feature, self.spatialReference)

    def rows(self):
        """returns Cursor.rows() as generator"""
        for feature in self.features:
            yield self.__createRow(feature, self.spatialReference).values

    def getRow(self, index):
        """returns row object at index"""
        return [r for r in self.get_rows()][index]

    def __validateOrderBy(self, fields):
        """fixes "fieldOrder" input fields, accepts esri field tokens too ("SHAPE@", "OID@")
        Required:
            fields -- list or comma delimited field list
        """
        if not fields or fields == '*':
            fields = [f.name for f in self.fields]
        if isinstance(fields, basestring):
            fields = fields.split(',')
        for i,f in enumerate(fields):
            if '@' in f:
                fields[i] = f.upper()
            if f == self.ShapeFieldName:
                fields[i] = SHAPE_TOKEN
            if f == self.OIDFieldName:
                fields[i] = OID_TOKEN

        return fields

    def __iter__(self):
        """returns Cursor.rows()"""
        return self.rows()

    def __createRow(self, feature, spatialReference):

        cursor = self

        class Row(object):
            """Class to handle Row object"""
            def __init__(self, feature, spatialReference):
                """Row object for Cursor
                Required:
                    feature -- features JSON object
                """
                self.feature = feature
                self.spatialReference = spatialReference

            @property
            def geometry(self):
                """returns a restapi.Geometry() object"""
                if GEOMETRY in self.feature:
                    gd = copy.deepcopy(self.feature.geometry)
                    gd[SPATIAL_REFERENCE] = cursor.json.spatialReference
                    return Geometry(gd)
                return None

            @property
            def oid(self):
                """returns the OID for row"""
                if cursor.OIDFieldName:
                    return self.get(cursor.OIDFieldName)
                return None

            @property
            def values(self):
                """returns values as tuple"""
                # fix date format in milliseconds to datetime.datetime()
                vals = []
                for i, field in enumerate(cursor.fieldOrder):
                    if field in cursor.date_fields:
                        vals.append(mil_to_date(self.feature.attributes[field]))
                    else:
                        if field == OID_TOKEN:
                            vals.append(self.oid)
                        elif field == SHAPE_TOKEN:
                            vals.append(self.geometry)
                        else:
                            vals.append(self.feature.attributes[field])

                return tuple(vals)

            def get(self, field):
                """gets an attribute by field name
                Required:
                    field -- name of field for which to get the value
                """
                return self.feature.attributes.get(field)

            def __getitem__(self, i):
                """allows for getting a field value by index"""
                return self.values[i]

        return Row(feature, spatialReference)

class ArcServer(RESTEndpoint):
    """Class to handle ArcGIS Server Connection"""
    def __init__(self, url, usr='', pw='', token='', proxy=None):
        super(ArcServer, self).__init__(url, usr, pw, token, proxy)
        self.service_cache = []

    def getService(self, name_or_wildcard):
        """method to return Service Object (MapService, FeatureService, GPService, etc).
        This method supports wildcards

        Required:
            name_or_wildcard -- service name or wildcard used to grab service name
                (ex: "moun_webmap_rest/mapserver" or "*moun*mapserver")
        """
        full_path = self.get_service_url(name_or_wildcard)
        if full_path:
            extension = full_path.split('/')[-1]
            if extension == 'MapServer':
                return MapService(full_path, token=self.token)
            elif extension == 'FeatureServer':
                 return FeatureService(full_path, token=self.token)
            elif extension == 'GPServer':
                 return GPService(full_path, token=self.token)
            elif extension == 'ImageServer':
                 return ImageService(full_path, token=self.token)
            elif extension == 'GeocodeServer':
                return Geocoder(full_path, token=self.token)
            else:
                raise NotImplementedError('restapi does not support "{}" services!')

    @property
    def mapServices(self):
        """list of all MapServer objects"""
        if not self.service_cache:
            self.service_cache = self.list_services()
        return [s for s in self.service_cache if s.endswith('MapServer')]

    @property
    def featureServices(self):
        """list of all MapServer objects"""
        if not self.service_cache:
            self.service_cache = self.list_services()
        return [s for s in self.service_cache if s.endswith('FeatureServer')]

    @property
    def imageServices(self):
        """list of all MapServer objects"""
        if not self.service_cache:
            self.service_cache = self.list_services()
        return [s for s in self.service_cache if s.endswith('ImageServer')]

    @property
    def gpServices(self):
        """list of all MapServer objects"""
        if not self.service_cache:
            self.service_cache = self.list_services()
        return [s for s in self.service_cache if s.endswith('GPServer')]


    def list_services(self, filterer=True):
        """returns a list of all services

        Optional:
            filterer -- default is true to exclude "Utilities" and "System" folders,
                set to false to list all services.
        """
        return list(self.iter_services(filterer))

    def iter_services(self, token='', filterer=True):
        """returns a generator for all services

        Required:
            service -- full path to a rest services directory

        Optional:
            token -- token to handle security (only required if security is enabled)
            filterer -- default is true to exclude "Utilities" and "System" folders,
                set to false to list all services.
        """
        self.service_cache = []
        for s in self.services:
            full_service_url = '/'.join([self.url, s[NAME], s[TYPE]])
            self.service_cache.append(full_service_url)
            yield full_service_url
        folders = self.folders
        if filterer:
            for fld in ('Utilities', 'System'):
                try:
                    folders.remove(fld)
                except: pass
        for s in folders:
            new = '/'.join([self.url, s])
            resp = POST(new, token=self.token)
            for serv in resp[SERVICES]:
                full_service_url =  '/'.join([self.url, serv[NAME], serv[TYPE]])
                self.service_cache.append(full_service_url)
                yield full_service_url

    def get_service_url(self, wildcard='*', _list=False):
        """method to return a service url

        Optional:
            wildcard -- wildcard used to grab service name (ex "moun*featureserver")
            _list -- default is false.  If true, will return a list of all services
                matching the wildcard.  If false, first match is returned.
        """
        if not self.service_cache:
            self.list_services()
        if '*' in wildcard:
            if wildcard == '*':
                return self.service_cache[0]
            else:
                if _list:
                    return [s for s in self.service_cache if fnmatch.fnmatch(s, wildcard)]
            for s in self.service_cache:
                if fnmatch.fnmatch(s, wildcard):
                    return s
        else:
            if _list:
                return [s for s in self.service_cache if wildcard.lower() in s.lower()]
            for s in self.service_cache:
                if wildcard.lower() in s.lower():
                    return s
        print('"{0}" not found in services'.format(wildcard))
        return ''

    def get_folders(self):
        """method to get folder objects"""
        folder_objects = []
        for folder in self.folders:
            folder_url = '/'.join([self.url, folder])
            folder_objects.append(Folder(folder_url, self.token))
        return folder_objects

    def walk(self, filterer=True):
        """method to walk through ArcGIS REST Services. ArcGIS Server only supports single
        folder heiarchy, meaning that there cannot be subdirectories within folders.

        Optional:
            filterer -- will filter Utilities, default is True. If
              false, will list all services.

        will return tuple of folders and services from the topdown.
        (root, folders, services) example:

        ags = restapi.ArcServer(url, username, password)
        for root, folders, services in ags.walk():
            print root
            print folders
            print services
            print '\n\n'
        """
        self.service_cache = []
        services = []
        for s in self.services:
            qualified_service = '/'.join([s[NAME], s[TYPE]])
            full_service_url = '/'.join([self.url, qualified_service])
            services.append(qualified_service)
            self.service_cache.append(full_service_url)
        folders = self.folders
        if filterer:
            for fld in ('Utilities', 'System'):
                try:
                    folders.remove(fld)
                except: pass
        yield (self.url, folders, services)

        for f in folders:
            new = '/'.join([self.url, f])
            endpt = POST(new, token=self.token)
            services = []
            for serv in endpt[SERVICES]:
                qualified_service = '/'.join([serv[NAME], serv[TYPE]])
                full_service_url = '/'.join([self.url, qualified_service])
                services.append(qualified_service)
                self.service_cache.append(full_service_url)
            yield (f, endpt[FOLDERS], services)

    def __iter__(self):
        """returns an generator for services"""
        return self.list_services()

    def __len__(self):
        """returns number of services"""
        return len(self.service_cache)

class MapServiceLayer(RESTEndpoint, SpatialReferenceMixin):
    """Class to handle advanced layer properties"""

    def __init__(self, url='', usr='', pw='', token='', proxy=None):
        super(MapServiceLayer, self).__init__(url, usr, pw, token, proxy)
        try:
            self.json[FIELDS] = [Field(f) for f in self.json[FIELDS]]
        except:
            self.fields = []

    @property
    def OID(self):
        """OID field object"""
        try:
            return [f for f in self.fields if f.type == OID][0]
        except:
            return None

    @property
    def SHAPE(self):
        """SHAPE field object"""
        try:
            return [f for f in self.fields if f.type == SHAPE][0]
        except:
            return None

    def list_fields(self):
        """method to list field names"""
        return [f.name for f in self.fields]

    def fix_fields(self, fields):
        """fixes input fields, accepts esri field tokens too ("SHAPE@", "OID@")

        Required:
            fields -- list or comma delimited field list
        """
        field_list = []
        if fields == '*':
            return fields
        elif isinstance(fields, basestring):
            fields = fields.split(',')
        if isinstance(fields, list):
            all_fields = self.list_fields()
            for f in fields:
                if '@' in f:
                    if f.upper() == SHAPE_TOKEN:
                        if self.SHAPE:
                            field_list.append(self.SHAPE.name)
                    elif f.upper() == OID_TOKEN:
                        if self.OID:
                            field_list.append(self.OID.name)
                else:
                    if f in all_fields:
                        field_list.append(f)
        return ','.join(field_list)

    def query_all(self, oid, max_recs, where='1=1', add_params={}, token=''):
        """generator to form where clauses to query all records.  Will iterate through "chunks"
        of OID's until all records have been returned (grouped by maxRecordCount)

        *Thanks to Wayne Whitley for the brilliant idea to use itertools.izip_longest()

        Required:
            layer_url -- full path to layer url
            oid -- oid field name
            max_recs -- maximum amount of records returned

        Optional:
            where -- where clause for OID selection
            add_params -- dictionary with any additional params you want to add
            token -- token to handle security (only required if security is enabled)
        """
        if isinstance(add_params, dict):
            add_params[RETURN_IDS_ONLY] = TRUE

        # get oids
        oids = sorted(self.query(where=where, add_params=add_params, token=token)[OBJECT_IDS])
        print('total records: {0}'.format(len(oids)))

        # set returnIdsOnly to False
        add_params[RETURN_IDS_ONLY] = FALSE

        # iterate through groups to form queries
        for each in izip_longest(*(iter(oids),) * max_recs):
            theRange = filter(lambda x: x != None, each) # do not want to remove OID "0"
            _min, _max = min(theRange), max(theRange)
            del each

            yield '{0} >= {1} and {0} <= {2}'.format(oid, _min, _max)

    def query(self, fields='*', where='1=1', add_params={}, records=None, get_all=False, f=JSON, kmz='', **kwargs):
        """query layer and get response as JSON

        Optional:
            fields -- fields to return. Default is "*" to return all fields
            where -- where clause
            add_params -- extra parameters to add to query string passed as dict
            records -- number of records to return.  Default is None to return all
                records within bounds of max record count unless get_all is True
            get_all -- option to get all records in layer.  This option may be time consuming
                because the ArcGIS REST API uses default maxRecordCount of 1000, so queries
                must be performed in chunks to get all records.
            kwargs -- extra parameters to add to query string passed as key word arguments,
                will override add_params***

        # default params for all queries
        params = {'returnGeometry' : 'true', 'outFields' : fields,
                  'where': where, 'f' : 'json'}
        """
        query_url = self.url + '/query'

        # default params
        params = {RETURN_GEOMETRY : TRUE, WHERE: where, F : f}

        for k,v in add_params.iteritems():
            params[k] = v

        for k,v in kwargs.iteritems():
            params[k] = v

        # check for tokens (only shape and oid)
        fields = self.fix_fields(fields)
        params[OUT_FIELDS] = fields

        # create kmz file if requested (does not support get_all parameter)
        if f == 'kmz':
            r = POST(query_url, params, ret_json=False, token=self.token)
            r.encoding = 'zlib_codec'

            # write kmz using codecs
            if not kmz:
                kmz = validate_name(os.path.join(os.path.expanduser('~'), 'Desktop', '{}.kmz'.format(self.name)))
            with codecs.open(kmz, 'wb') as f:
                f.write(r.content)
            print('Created: "{0}"'.format(kmz))
            return kmz

        else:

            server_response = {}

            if get_all:
                records = None
                max_recs = self.json.get(MAX_RECORD_COUNT)
                if not max_recs:
                    # guess at 500 (default 1000 limit cut in half at 10.0 if returning geometry)
                    max_recs = 500

                for i, where2 in enumerate(self.query_all(oid_name, max_recs, where, add_params, self.token)):
                    sql = ' and '.join(filter(None, [where.replace('1=1', ''), where2])) #remove default
                    resp = POST(query_url, params, token=self.token)
                    if i < 1:
                        server_response = resp
                    else:
                        server_response[FEATURES] += resp[FEATURES]

            else:
                server_response = POST(query_url, params, token=self.token)

            if all([server_response.get(k) for k in (FIELDS, FEATURES, GEOMETRY_TYPE)]):
                if records:
                    server_response[FEATURES] = server_response[FEATURES][:records]
                return FeatureSet(server_response)
            else:
                if records:
                    if isinstance(server_response, list):
                        return server_response[:records]
                return server_response

    def select_by_location(self, geometry, geometryType='', inSR='', spatialRel=ESRI_INTERSECT, distance=0, units=ESRI_METER, add_params={}, **kwargs):
        """Selects features by location of a geometry, returns a feature set

        Required:
            geometry -- geometry as JSON

        Optional:
            geometryType -- type of geometry object, this can be gleaned automatically from the geometry input
            inSR -- input spatial reference
            spatialRel -- spatial relationship applied on the input geometry when performing the query operation
            distance -- distance for search
            units -- units for distance, only used if distance > 0 and if supportsQueryWithDistance is True
            add_params -- dict containing any other options that will be added to the query
            kwargs -- keyword args to add to the query


        Spatial Relationships:
            esriSpatialRelIntersects | esriSpatialRelContains | esriSpatialRelCrosses | esriSpatialRelEnvelopeIntersects | esriSpatialRelIndexIntersects
            | esriSpatialRelOverlaps | esriSpatialRelTouches | esriSpatialRelWithin | esriSpatialRelRelation

        Unit Options:
            esriSRUnit_Meter | esriSRUnit_StatuteMile | esriSRUnit_Foot | esriSRUnit_Kilometer | esriSRUnit_NauticalMile | esriSRUnit_USNauticalMile
        """
        if isinstance(geometry, basestring):
            geometry = json.loads(geometry)

        if not geometryType:
            for key,gtype in GEOM_DICT.iteritems():
                if key in geometry:
                    geometryType = gtype
                    break

        if SPATIAL_REFERENCE in geometry:
            sr_dict = geometry[SPATIAL_REFERENCE]
            inSR = sr_dict.get(LATEST_WKID) if sr_dict.get(LATEST_WKID) else sr_dict.get(WKID)

        params = {GEOMETRY: geometry,
                  GEOMETRY_TYPE: geometryType,
                  SPATIAL_REL: spatialRel,
                  IN_SR: inSR,
            }

        if int(distance):
            params[DISTANCE] = distance
            params[UNITS] = units

        # add additional params
        for k,v in add_params.iteritems():
            if k not in params:
                params[k] = v

        # add kwargs
        for k,v in kwargs.iteritems():
            if k not in params:
                params[k] = v

        return FeatureSet(self.query(add_params=params))

    def layer_to_kmz(self, out_kmz='', flds='*', where='1=1', params={}):
        """Method to create kmz from query

        Optional:
            out_kmz -- output kmz file path, if none specified will be saved on Desktop
            flds -- list of fields for fc. If none specified, all fields are returned.
                Supports fields in list [] or comma separated string "field1,field2,.."
            where -- optional where clause
            params -- dictionary of parameters for query
        """
        return query(self.url, flds, where=where, add_params=params, ret_form='kmz', token=self.token, kmz=out_kmz)

    def getOIDs(self, where='1=1', max_recs=None, **kwargs):
        """return a list of OIDs from feature layer

        Optional:
            where -- where clause for OID selection
            max_recs -- maximimum number of records to return (maxRecordCount does not apply)
            **kwargs -- optional key word arguments to further limit query (i.e. add geometry interesect)
        """
        p = {RETURN_IDS_ONLY:TRUE,
             RETURN_GEOMETRY: FALSE,
             OUT_FIELDS: ''}

        # add kwargs if specified
        for k,v in kwargs.iteritems():
            if k not in p.keys():
                p[k] = v

        return sorted(self.query(where=where, add_params=p)[OBJECT_IDS])[:max_recs]

    def getCount(self, where='1=1', **kwargs):
        """get count of features, can use optional query and **kwargs to filter

        Optional:
            where -- where clause
            kwargs -- keyword arguments for query operation
        """
        return len(self.getOIDs(where,  **kwargs))

    def attachments(self, oid, gdbVersion=''):
        """query attachments for an OBJECTDID

        Required:
            oid -- object ID

        Optional:
            gdbVersion -- Geodatabase version to query, only supported if self.isDataVersioned is true
        """
        if self.hasAttachments:
            query_url = '{0}/{1}/attachments'.format(self.url, oid)
            r = POST(query_url, cookies=self._cookie)

            add_tok = ''
            if self.token:
                add_tok = '?token={}'.format(self.token.token if isinstance(self.token, Token) else self.token)

            if ATTACHMENT_INFOS in r:
                for attInfo in r[ATTACHMENT_INFOS]:
                    attInfo[URL] = '{}/{}'.format(query_url, attInfo[ID])
                    attInfo[URL_WITH_TOKEN] = '{}/{}{}'.format(query_url, attInfo[ID], add_tok)

                class Attachment(namedtuple('Attachment', 'id name size contentType url urlWithToken')):
                    """class to handle Attachment object"""
                    __slots__ = ()
                    def __new__(cls,  **kwargs):
                        return super(Attachment, cls).__new__(cls, **kwargs)

                    def __repr__(self):
                        if hasattr(self, ID) and hasattr(self, NAME):
                            return '<Attachment ID: {} ({})>'.format(self.id, self.name)
                        else:
                            return '<Attachment> ?'

                    def download(self, out_path, name='', verbose=True):
                        """download the attachment to specified path

                        out_path -- output path for attachment

                        optional:
                            name -- name for output file.  If left blank, will be same as attachment.
                            verbose -- if true will print sucessful download message
                        """
                        if not name:
                            out_file = assignUniqueName(os.path.join(out_path, self.name))
                        else:
                            ext = os.path.splitext(self.name)[-1]
                            out_file = os.path.join(out_path, name.split('.')[0] + ext)

                        with open(out_file, 'wb') as f:
                            f.write(urllib.urlopen(self.url).read())

                        if verbose:
                            print('downloaded attachment "{}" to "{}"'.format(self.name, out_path))
                        return out_file

                return [Attachment(**a) for a in r[ATTACHMENT_INFOS]]

            return []

        else:
            raise NotImplementedError('Layer "{}" does not support attachments!'.format(self.name))

    def cursor(self, fields='*', where='1=1', add_params={}, records=None, get_all=False):
        """Run Cursor on layer, helper method that calls Cursor Object"""
        cur_fields = self.fix_fields(fields)

        fs = self.query(cur_fields, where, add_params, records, get_all)
        return Cursor(fs, fields)

    def layer_to_fc(self, out_fc, fields='*', where='1=1', records=None, params={}, get_all=False, sr=None):
        """Method to export a feature class from a service layer

        Required:
            out_fc -- full path to output feature class

        Optional:
            where -- optional where clause
            params -- dictionary of parameters for query
            fields -- list of fields for fc. If none specified, all fields are returned.
                Supports fields in list [] or comma separated string "field1,field2,.."
            records -- number of records to return. Default is none, will return maxRecordCount
            get_all -- option to get all records.  If true, will recursively query REST endpoint
                until all records have been gathered. Default is False.
            sr -- output spatial refrence (WKID)
        """
        if self.type == 'Feature Layer':
            if not fields:
                fields = '*'
            if fields == '*':
                _fields = self.fields
            else:
                if isinstance(fields, basestring):
                    fields = fields.split(',')
                _fields = [f for f in self.fields if f.name in fields]

            # filter fields for cusor object
            cur_fields = []
            for fld in _fields:
                if fld.type not in [OID] + SKIP_FIELDS.keys():
                    if not any(['shape_' in fld.name.lower(),
                                'shape.' in fld.name.lower(),
                                '(shape)' in fld.name.lower(),
                                'objectid' in fld.name.lower(),
                                fld.name.lower() == 'fid']):
                        cur_fields.append(fld.name)

            # make new feature class
            if not sr:
                sr = self.getSR()
            else:
                params[OUT_SR] = sr

            # do query to get feature set
            fs = self.query(cur_fields, where, params, records, get_all)

            return exportFeatureSet(fs, out_fc)

        else:
            print('Layer: "{}" is not a Feature Layer!'.format(self.name))

    def clip(self, poly, output, fields='*', out_sr='', where='', envelope=False):
        """Method for spatial Query, exports geometry that intersect polygon or
        envelope features.

        Required:
            poly -- polygon (or other) features used for spatial query
            output -- full path to output feature class

        Optional:
             fields -- list of fields for fc. If none specified, all fields are returned.
                Supports fields in list [] or comma separated string "field1,field2,.."
            out_sr -- output spatial refrence (WKID)
            where -- optional where clause
            envelope -- if true, the polygon features bounding box will be used.  This option
                can be used if the feature has many vertices or to check against the full extent
                of the feature class
        """
        if isinstance(poly, Geometry):
            in_geom = poly
        else:
            in_geom = Geometry(poly)
        sr = in_geom.spatialReference
        if envelope:
            geojson = in_geom.envelopeAsJSON()
            geometryType = ESRI_ENVELOPE
        else:
            geojson = in_geom.dumps()
            geometryType = in_geom.geometryType

        if not out_sr:
            out_sr = sr

        d = {GEOMETRY_TYPE: geometryType,
             RETURN_GEOMETRY: TRUE,
             GEOMETRY: geojson,
             IN_SR : sr,
             OUT_SR: out_sr}

        return self.layer_to_fc(output, fields, where, params=d, get_all=True, sr=out_sr)

    def __repr__(self):
        """string representation with service name"""
        return '<{}: "{}" (id: {})>'.format(self.__class__.__name__, self.name, self.id)

class MapService(BaseService):

    def getLayerIdByName(self, name, grp_lyr=False):
        """gets a mapservice layer ID by layer name from a service (returns an integer)

        Required:
            name -- name of layer from which to grab ID

        Optional:
            grp_lyr -- default is false, does not return layer ID for group layers.  Set
                to true to search for group layers too.
        """
        all_layers = self.layers
        for layer in all_layers:
            if fnmatch.fnmatch(layer[NAME], name):
                if SUB_LAYER_IDS in layer:
                    if grp_lyr and layer[SUB_LAYER_IDS] != None:
                        return layer[ID]
                    elif not grp_lyr and not layer[SUB_LAYER_IDS]:
                        return layer[ID]
                return layer[ID]
        for tab in r[TABLES]:
            if fnmatch.fnmatch(tab[NAME], name):
                return tab[ID]
        print('No Layer found matching "{0}"'.format(name))
        return None

    def get_layer_url(self, name, grp_lyr=False):
        """returns the fully qualified path to a layer url by pattern match on name,
        will return the first match.

        Required:
            name -- name of layer from which to grab ID

        Optional:
            grp_lyr -- default is false, does not return layer ID for group layers.  Set
                to true to search for group layers too.
        """
        return '/'.join([self.url, str(self.getLayerIdByName(name,grp_lyr))])

    def list_layers(self):
        """Method to return a list of layer names in a MapService"""
        return [l.name for l in self.layers]

    def list_tables(self):
        """Method to return a list of layer names in a MapService"""
        return [t.name for t in self.tables]

    def getNameFromId(self, lyrID):
        """method to get layer name from ID

        Required:
            lyrID -- id of layer for which to get name
        """
        return [l.name for l in self.layers if l.id == lyrID][0]

    def export(self, out_image, imageSR=None, bbox=None, bboxSR=None, size=None, dpi=96, format='png8', transparent=True, **kwargs):
        """exports a map image

        Required:
            out_image -- full path to output image

        Optional:
            imageSR -- spatial reference for exported image
            bbox -- bounding box as comma separated string
            bboxSR -- spatial reference for bounding box
            size -- comma separated string for the size of image in pixels. It is advised not to use
                this parameter and let this method generate it automatically
            dpi -- output resolution, default is 96
            format -- image format, default is png8
            transparent -- option to support transparency in exported image, default is True
            kwargs -- any additional keyword arguments for export operation (must be supported by REST API)

        Keyword Arguments can be found here:
            http://resources.arcgis.com/en/help/arcgis-rest-api/index.html#/Export_Map/02r3000000v7000000/
        """
        query_url = self.url + '/export'

        # defaults if params not specified
        if bbox and not size:
            if isinstance(bbox, (list, tuple)):
                size = ','.join([abs(int(bbox[0]) - int(bbox[2])), abs(int(bbox[1]) - int(bbox[3]))])
        if not bbox:
            ie = self.initialExtent
            bbox = ','.join(map(str, [ie.xmin, ie.ymin, ie.xmax, ie.ymax]))

            if not size:
                size = ','.join(map(str, [abs(int(ie.xmin) - int(ie.xmax)), abs(int(ie.ymin) - int(ie.ymax))]))

            bboxSR = self.spatialReference

        if not imageSR:
            imageSR = self.spatialReference

        # initial params
        params = {FORMAT: format,
          F: IMAGE,
          IMAGE_SR: imageSR,
          BBOX_SR: bboxSR,
          BBOX: bbox,
          TRANSPARENT: transparent,
          DPI: dpi,
          SIZE: size}

        # add additional params from **kwargs
        for k,v in kwargs.iteritems():
            if k not in params:
                params[k] = v

        # do post
        r = POST(query_url, params, ret_json=False)

        # save image
        with open(out_image, 'wb') as f:
            f.write(r.content)

        return r

    def layer(self, name_or_id):
        """Method to return a layer object with advanced properties by name

        Required:
            name -- layer name (supports wildcard syntax*) or id (must be of type <int>)
        """
        if isinstance(name_or_id, int):
            # reference by id directly
            return MapServiceLayer('/'.join([self.url, str(name_or_id)]), token=self.token)

        layer_path = self.get_layer_url(name_or_id, self.token)
        if layer_path:
            return MapServiceLayer(layer_path, token=self.token)
        else:
            print('Layer "{0}" not found!'.format(name_or_id))

    def cursor(self, layer_name, fields='*', where='1=1', records=None, add_params={}, get_all=False):
        """Cusor object to handle queries to rest endpoints

        Required:
           layer_name -- name of layer in map service

        Optional:
            fields -- option to limit fields returned.  All are returned by default
            where -- where clause for cursor
            records -- number of records to return (within bounds of max record count)
            token --
            add_params -- option to add additional search parameters
            get_all -- option to get all records in layer.  This option may be time consuming
                because the ArcGIS REST API uses default maxRecordCount of 1000, so queries
                must be performed in chunks to get all records
        """
        lyr = self.layer(layer_name)
        return lyr.cursor(fields, where, add_params, records, get_all)

    def layer_to_fc(self, layer_name,  out_fc, fields='*', where='1=1',
                    records=None, params={}, get_all=False, sr=None):
        """Method to export a feature class from a service layer

        Required:
            layer_name -- name of map service layer to export to fc
            out_fc -- full path to output feature class

        Optional:
            where -- optional where clause
            params -- dictionary of parameters for query
            fields -- list of fields for fc. If none specified, all fields are returned.
                Supports fields in list [] or comma separated string "field1,field2,.."
            records -- number of records to return. Default is none, will return maxRecordCount
            get_all -- option to get all records.  If true, will recursively query REST endpoint
                until all records have been gathered. Default is False.
            sr -- output spatial refrence (WKID)
        """
        lyr = self.layer(layer_name)
        lyr.layer_to_fc(out_fc, fields, where,records, params, get_all, sr)

    def layer_to_kmz(self, layer_name, out_kmz='', flds='*', where='1=1', params={}):
        """Method to create kmz from query

        Required:
            layer_name -- name of map service layer to export to fc

        Optional:
            out_kmz -- output kmz file path, if none specified will be saved on Desktop
            flds -- list of fields for fc. If none specified, all fields are returned.
                Supports fields in list [] or comma separated string "field1,field2,.."
            where -- optional where clause
            params -- dictionary of parameters for query
        """
        lyr = self.layer(layer_name)
        lyr.layer_to_kmz(flds, where, params, kmz=out_kmz)

    def clip(self, layer_name, poly, output, fields='*', out_sr='', where='', envelope=False):
        """Method for spatial Query, exports geometry that intersect polygon or
        envelope features.

        Required:
            layer_name -- name of map service layer to export to fc
            poly -- polygon (or other) features used for spatial query
            output -- full path to output feature class

        Optional:
             fields -- list of fields for fc. If none specified, all fields are returned.
                Supports fields in list [] or comma separated string "field1,field2,.."
            sr -- output spatial refrence (WKID)
            where -- optional where clause
            envelope -- if true, the polygon features bounding box will be used.  This option
                can be used if the feature has many vertices or to check against the full extent
                of the feature class
        """
        lyr = self.layer(layer_name)
        return lyr.clip(poly, output, fields, out_sr, where, envelope)

    def __iter__(self):
        for lyr in self.layers:
            yield lyr

class FeatureService(MapService):
    """class to handle Feature Service

    Required:
        url -- image service url

    Optional (below params only required if security is enabled):
        usr -- username credentials for ArcGIS Server
        pw -- password credentials for ArcGIS Server
        token -- token to handle security (alternative to usr and pw)
        proxy -- option to use proxy page to handle security, need to provide
            full path to proxy url.
    """

    @property
    def replicas(self):
        """returns a list of replica objects"""
        if self.syncEnabled:
            reps = POST(self.url + '/replicas', cookies=self._cookie)
            return [namedTuple('Replica', r) for r in reps]
        else:
            return []

    def layer(self, name_or_id):
        """Method to return a layer object with advanced properties by name

        Required:
            name -- layer name (supports wildcard syntax*) or layer id (int)
        """
        if isinstance(name_or_id, int):
            # reference by id directly
            return FeatureLayer('/'.join([self.url, str(name_or_id)]), token=self.token)

        layer_path = self.get_layer_url(name_or_id)
        if layer_path:
            return FeatureLayer(layer_path, token=self.token)
        else:
            print('Layer "{0}" not found!'.format(name_or_id))

    def layer_to_kmz(self, layer_name, out_kmz='', flds='*', where='1=1', params={}):
        """Method to create kmz from query

        Required:
            layer_name -- name of map service layer to export to fc

        Optional:
            out_kmz -- output kmz file path, if none specified will be saved on Desktop
            flds -- list of fields for fc. If none specified, all fields are returned.
                Supports fields in list [] or comma separated string "field1,field2,.."
            where -- optional where clause
            params -- dictionary of parameters for query
        """
        lyr = self.layer(layer_name)
        lyr.layer_to_kmz(flds, where, params, kmz=out_kmz)

    def createReplica(self, layers, replicaName, geometry='', geometryType='', inSR='', replicaSR='', **kwargs):
        """query attachments, returns a JSON object

        Required:
            layers -- list of layers to create replicas for (valid inputs below)
            replicaName -- name of replica

        Optional:
            geometry -- optional geometry to query features
            geometryType -- type of geometry
            inSR -- input spatial reference for geometry
            replicaSR -- output spatial reference for replica data
            **kwargs -- optional keyword arguments for createReplica request
        """
        if hasattr(self, SYNC_ENABLED) and not self.syncEnabled:
            raise NotImplementedError('FeatureService "{}" does not support Sync!'.format(self.url))

        # validate layers
        if isinstance(layers, basestring):
            layers = [l.strip() for l in layers.split(',')]

        elif not isinstance(layers, (list, tuple)):
            layers = [layers]

        if all(map(lambda x: isinstance(x, int), layers)):
            layers = ','.join(map(str, layers))

        elif all(map(lambda x: isinstance(x, basestring), layers)):
            layers = ','.join(map(str, filter(lambda x: x is not None,
                                [s.id for s in self.layers if s.name.lower()
                                 in [l.lower() for l in layers]])))

        if not geometry and not geometryType:
            ext = self.initialExtent
            inSR = self.initialExtent.spatialReference
            geometry= ','.join(map(str, [ext.xmin,ext.ymin,ext.xmax,ext.ymax]))
            geometryType = ESRI_ENVELOPE
            inSR = self.spatialReference
            useGeometry = False
        else:
            useGeometry = True
            if isinstance(geometry, dict) and SPATIAL_REFERENCE in geometry and not inSR:
                inSR = geometry[SPATIAL_REFERENCE]


        if not replicaSR:
            replicaSR = self.spatialReference

        validated = layers.split(',')
        options = {REPLICA_NAME: replicaName,
                   LAYERS: layers,
                   LAYER_QUERIES: '',
                   GEOMETRY: geometry,
                   GEOMETRY_TYPE: geometryType,
                   IN_SR: inSR,
                   REPLICA_SR:	replicaSR,
                   TRANSPORT_TYPE: TRANSPORT_TYPE_URL,
                   RETURN_ATTACHMENTS:	TRUE,
                   RETURN_ATTACHMENTS_DATA_BY_URL: TRUE,
                   ASYNC:	FALSE,
                   F: PJSON,
                   DATA_FORMAT: JSON,
                   REPLICA_OPTIONS: '',
                   }

        for k,v in kwargs.iteritems():
            options[k] = v
            if k == LAYER_QUERIES:
                if options[k]:
                    if isinstance(options[k], basestring):
                        options[k] = json.loads(options[k])
                    for key in options[k].keys():
                        options[k][key][USE_GEOMETRY] = useGeometry
                        options[k] = json.dumps(options[k])

        if self.syncCapabilities.supportsPerReplicaSync:
            options[SYNC_MODEL] = PER_REPLICA
        else:
            options[SYNC_MODEL] = PER_LAYER

        if options[ASYNC] in (TRUE, True) and self.syncCapabilities.supportsAsync:
            st = POST(self.url + '/createReplica', options, cookies=self._cookie)
            while STATUS_URL not in st:
                time.sleep(1)
        else:
            options[ASYNC] = 'false'
            st = POST(self.url + '/createReplica', options, cookies=self._cookie)

        RequestError(st)
        js = POST(st['URL'] if 'URL' in st else st[STATUS_URL], cookies=self._cookie)
        RequestError(js)

        if not replicaSR:
            replicaSR = self.spatialReference

        repLayers = []
        for i,l in enumerate(js[LAYERS]):
            l[LAYER_URL] = '/'.join([self.url, validated[i]])
            layer_ob = FeatureLayer(l[LAYER_URL], token=self.token)
            l[FIELDS] = layer_ob.fields
            l[NAME] = layer_ob.name
            l[GEOMETRY_TYPE] = layer_ob.geometryType
            l[SPATIAL_REFERENCE] = replicaSR
            if not ATTACHMENTS in l:
                l[ATTACHMENTS] = []
            repLayers.append(namedTuple('ReplicaLayer', l))

        rep_dict = js
        rep_dict[LAYERS] = repLayers
        return namedTuple('Replica', rep_dict)

    def replicaInfo(self, replicaID):
        """get replica information

        Required:
            replicaID -- ID of replica
        """
        query_url = self.url + '/replicas/{}'.format(replicaID)
        return namedTuple('ReplicaInfo', POST(query_url, cookies=self._cookie))

    def syncReplica(self, replicaID, **kwargs):
        """synchronize a replica.  Must be called to sync edits before a fresh replica
        can be obtained next time createReplica is called.  Replicas are snapshots in
        time of the first time the user creates a replica, and will not be reloaded
        until synchronization has occured.  A new version is created for each subsequent
        replica, but it is cached data.

        It is also recommended to unregister a replica
        AFTER sync has occured.  Alternatively, setting the "closeReplica" keyword
        argument to True will unregister the replica after sync.

        More info can be found here:
            http://server.arcgis.com/en/server/latest/publish-services/windows/prepare-data-for-offline-use.htm

        and here for key word argument parameters:
            http://resources.arcgis.com/en/help/arcgis-rest-api/index.html#/Synchronize_Replica/02r3000000vv000000/

        Required:
            replicaID -- ID of replica
        """
        query_url = self.url + '/synchronizeReplica'
        params = {REPLICA_ID: replicaID}

        for k,v in kwargs.iteritems():
            params[k] = v

        return POST(query_url, params, cookies=self._cookie)


    def unRegisterReplica(self, replicaID):
        """unregisters a replica on the feature service

        Required:
            replicaID -- the ID of the replica registered with the service
        """
        query_url = self.url + '/unRegisterReplica'
        params = {REPLICA_ID: replicaID}
        return POST(query_url, params, cookies=self._cookie)

class FeatureLayer(MapServiceLayer):
    def __init__(self, url='', usr='', pw='', token='', proxy=None):
        """class to handle Feature Service Layer

        Required:
            url -- image service url

        Optional (below params only required if security is enabled):
            usr -- username credentials for ArcGIS Server
            pw -- password credentials for ArcGIS Server
            token -- token to handle security (alternative to usr and pw)
            proxy -- option to use proxy page to handle security, need to provide
                full path to proxy url.
        """
        super(FeatureLayer, self).__init__(url, usr, pw, token, proxy)

        # store list of EditResult() objects to track changes
        self.editResults = []

    def addFeatures(self, features, gdbVersion='', rollbackOnFailure=True):
        """add new features to feature service layer

        features -- esri JSON representation of features

        ex:
        adds = [{"geometry":
                     {"x":-10350208.415443439,
                      "y":5663994.806146532,
                      "spatialReference":
                          {"wkid":102100}},
                 "attributes":
                     {"Utility_Type":2,"Five_Yr_Plan":"No","Rating":None,"Inspection_Date":1429885595000}}]
        """
        add_url = self.url + '/addFeatures'
        params = {FEATURES: json.dumps(features) if isinstance(features, list) else features,
                  GDB_VERSION: gdbVersion,
                  ROLLBACK_ON_FAILURE: rollbackOnFailure,
                  F: PJSON}

        # add features
        return self.__edit_handler(POST(add_url, params, cookies=self._cookie))

    def updateFeatures(self, features, gdbVersion='', rollbackOnFailure=True):
        """update features in feature service layer

        Required:
            features -- features to be updated (JSON)

        Optional:
            gdbVersion -- geodatabase version to apply edits
            rollbackOnFailure -- specify if the edits should be applied only if all submitted edits succeed

        # example syntax
        updates = [{"geometry":
                {"x":-10350208.415443439,
                 "y":5663994.806146532,
                 "spatialReference":
                     {"wkid":102100}},
            "attributes":
                {"Five_Yr_Plan":"Yes","Rating":90,"OBJECTID":1}}] #only fields that were changed!
        """
        update_url = self.url + '/updateFeatures'
        params = {FEATURES: json.dumps(features),
                  GDB_VERSION: gdbVersion,
                  ROLLBACK_ON_FAILURE: rollbackOnFailure,
                  F: JSON}

        # update features
        return self.__edit_handler(POST(update_url, params, cookies=self._cookie))

    def deleteFeatures(self, oids='', where='', geometry='', geometryType='',
                       spatialRel='', inSR='', gdbVersion='', rollbackOnFailure=True):
        """deletes features based on list of OIDs

        Optional:
            oids -- list of oids or comma separated values
            where -- where clause for features to be deleted.  All selected features will be deleted
            geometry -- geometry JSON object used to delete features.
            geometryType -- type of geometry
            spatialRel -- spatial relationship.  Default is "esriSpatialRelationshipIntersects"
            inSR -- input spatial reference for geometry
            gdbVersion -- geodatabase version to apply edits
            rollbackOnFailure -- specify if the edits should be applied only if all submitted edits succeed

        oids format example:
            oids = [1, 2, 3] # list
            oids = "1, 2, 4" # as string
        """
        if not geometryType:
            geometryType = ESRI_ENVELOPE
        if not spatialRel:
            spatialRel = ESRI_INTERSECT

        del_url = self.url + '/deleteFeatures'
        if isinstance(oids, (list, tuple)):
            oids = ', '.join(map(str, oids))
        params = {OBJECT_IDS: oids,
                  WHERE: where,
                  GEOMETRY: geometry,
                  GEOMETRY_TYPE: geometryType,
                  SPATIAL_REL: spatialRel,
                  GDB_VERSION: gdbVersion,
                  ROLLBACK_ON_FAILURE: rollbackOnFailure,
                  F: JSON}

        # delete features
        return self.__edit_handler(POST(del_url, params, cookies=self._cookie))

    def applyEdits(self, adds=None, updates=None, deletes=None, gdbVersion=None, rollbackOnFailure=TRUE):
        """apply edits on a feature service layer

        Optional:
            adds -- features to add (JSON)
            updates -- features to be updated (JSON)
            deletes -- oids to be deleted (list, tuple, or comma separated string)
            gdbVersion -- geodatabase version to apply edits
            rollbackOnFailure -- specify if the edits should be applied only if all submitted edits succeed
        """
        edits_url = self.url + '/applyEdits'
        if isinstance(adds, FeatureSet):
            adds = adds.features
        if isinstance(updates, FeatureSet):
            updates = updates.features
        params = {ADDS: adds,
                  UPDATES: updates,
                  DELETES: deletes,
                  GDB_VERSION: gdbVersion,
                  ROLLBACK_ON_FAILURE: rollbackOnFailure
        }
        return self.__edit_handler(POST(edits_url, params, cookies=self._cookie))

    def addAttachment(self, oid, attachment, content_type='', gdbVersion=''):
        """add an attachment to a feature service layer

        Required:
            oid -- OBJECT ID of feature in which to add attachment
            attachment -- path to attachment

        Optional:
            content_type -- html media type for "content_type" header.  If nothing provided,
                will use a best guess based on file extension (using mimetypes)
            gdbVersion -- geodatabase version for attachment

            valid content types can be found here @:
                http://en.wikipedia.org/wiki/Internet_media_type
        """
        if self.hasAttachments:

            # use mimetypes to guess "content_type"
            if not content_type:
                content_type = mimetypes.guess_type(os.path.basename(attachment))[0]
                if not content_type:
                    known = mimetypes.types_map
                    common = mimetypes.common_types
                    ext = os.path.splitext(attachment)[-1].lower()
                    if ext in known:
                        content_type = known[ext]
                    elif ext in common:
                        content_type = common[ext]

            # make post request
            att_url = '{}/{}/addAttachment'.format(self.url, oid)
            files = {ATTACHMENT: (os.path.basename(attachment), open(attachment, 'rb'), content_type)}
            params = {F: JSON}
            if gdbVersion:
                params[GDB_VERSION] = gdbVersion
            return self.__edit_handler(requests.post(att_url, params, files=files, cookies=self._cookie, verify=False).json(), oid)

        else:
            raise NotImplementedError('FeatureLayer "{}" does not support attachments!'.format(self.name))

    def calculate(self, exp, where='1=1', sqlFormat='standard'):
        """calculate a field in a Feature Layer

        Required:
            exp -- expression as JSON [{"field": "Street", "value": "Main St"},..]

        Optional:
            where -- where clause for field calculator
            sqlFormat -- SQL format for expression (standard|native)

        Example expressions as JSON:
            exp = [{"field" : "Quality", "value" : 3}]
            exp =[{"field" : "A", "sqlExpression" : "B*3"}]
        """
        if hasattr(self, SUPPORTS_CALCULATE) and self.supportsCalculate:
            calc_url = self.url + '/calculate'
            p = {RETURN_IDS_ONLY:TRUE,
                RETURN_GEOMETRY: 'false',
                OUT_FIELDS: '',
                CALC_EXPRESSION: json.dumps(exp),
                SQL_FORMAT: sqlFormat}

            return POST(calc_url, where=where, add_params=p, cookies=self._cookie)

        else:
            raise NotImplementedError('FeatureLayer "{}" does not support field calculations!'.format(self.name))

    def __edit_handler(self, response, feature_id=None):
        """hanlder for edit results

        response -- response from edit operation
        """
        e = EditResult(response, feature_id)
        self.editResults.append(e)
        e.summary()
        return e

class GeometryService(RESTEndpoint):
    linear_units = sorted(LINEAR_UNITS.keys())
    _default_url = 'https://utility.arcgisonline.com/ArcGIS/rest/services/Geometry/GeometryServer'

    def __init__(self, url=None, usr=None, pw=None, token=None, proxy=None):
        if not url:
            # do not require a url, use default arcgis online Geometry Service
            super(GeometryService, self).__init__(self._default_url, usr, pw, token, proxy)
        else:
            super(GeometryService, self).__init__(url, usr, pw, token, proxy)

    @staticmethod
    def getLinearUnitWKID(unit_name):
        """gets a well known ID from a unit name

        Required:
            unit_name -- name of unit to fetch WKID for.  It is safe to use this as
                a filter to ensure a valid WKID is extracted.  if a WKID is passed in,
                that same value is returned.  This argument is expecting a string from
                linear_units list.  Valid options can be viewed with GeometryService.linear_units
        """
        if isinstance(unit_name, int) or unicode(unit_name).isdigit():
            return int(unit_name)

        for k,v in LINEAR_UNITS.iteritems():
            if k.lower() == unit_name.lower():
                return int(v[WKID])

    @staticmethod
    def validateGeometries(geometries, use_envelopes=False):
        """validates geometries to be passed into operations that use an
        array of geometries.

        Required:
            geometries -- list of geometries.  Valid inputs are GeometryCollection()'s, json,
                FeatureSet()'s, or Geometry()'s.
            use_envelopes -- option to use envelopes of all the input geometires
        """
        gc = GeometryCollection(geometries, use_envelopes)
        return gc.json

    @geometry_passthrough
    def buffer(self, geometries, inSR, distances, unit='', outSR='', use_envelopes=False, **kwargs):
        """buffer a single geoemetry or multiple

        Required:
            geometries -- array of geometries to be buffered. The spatial reference of the geometries
                is specified by inSR. The structure of each geometry in the array is the same as the
                structure of the JSON geometry objects returned by the ArcGIS REST API.

            inSR -- wkid for input geometry

            distances -- the distances that each of the input geometries is buffered. The distance units
                are specified by unit.

        Optional:

            use_envelopes -- not a valid option in ArcGIS REST API, this is an extra argument that will
                convert the geometries to bounding box envelopes ONLY IF they are restapi.Geometry objects,
                otherwise this parameter is ignored.
        """
        buff_url = self.url + '/buffer'

        params = {F: PJSON,
                  GEOMETRIES: self.validateGeometries(geometries),
                  IN_SR: inSR,
                  DISTANCES: distances,
                  UNIT: self.getLinearUnitWKID(unit),
                  OUT_SR: outSR,
                  UNION_RESULTS: FALSE,
                  GEODESIC: FALSE,
                  OUT_SR: None,
                  BUFFER_SR: None
        }

        # add kwargs
        for k,v in kwargs.iteritems():
            if k not in (GEOMETRIES, DISTANCES, UNIT):
                params[k] = v

        # perform operation
        gc = GeometryCollection(POST(buff_url, params, cookies=self._cookie))
        gc.spatialReference = outSR if outSR else inSR
        return gc

    @geometry_passthrough
    def intersect(self, geometries, geometry, sr):
        """performs intersection of input geometries and other geometry

        """
        query_url = self.url + '/intersect'
        geometry = Geometry(geometry)
        geojson = {GEOMETRY_TYPE: geometry.geometryType, GEOMETRY: geometry.json}
        geometries = self.validateGeometries(geometries)
        sr = geometries.spatialReference

        params = {GEOMETRY: geometry,
                  GEOMETRIES: geometries,
                  SR: sr
        }
        gc = POST(query_url, params, cookies=self._cookie)
        gc.spatialReference = sr
        return gc

    def findTransformations(self, inSR, outSR, extentOfInterest='', numOfResults=1):
        """finds the most applicable transformation based on inSR and outSR

        Required:
            inSR -- input Spatial Reference (wkid)
            outSR -- output Spatial Reference (wkid)

        Optional:
            extentOfInterest --e bounding box of the area of interest specified as a
                JSON envelope. If provided, the extent of interest is used to return
                the most applicable geographic transformations for the area. If a spatial
                reference is not included in the JSON envelope, the inSR is used for the
                envelope.

            numOfResults -- The number of geographic transformations to return. The
                default value is 1. If numOfResults has a value of -1, all applicable
                transformations are returned.

        return looks like this:
            [
              {
                "wkid": 15851,
                "latestWkid": 15851,
                "name": "NAD_1927_To_WGS_1984_79_CONUS"
              },
              {
                "wkid": 8072,
                "latestWkid": 1172,
                "name": "NAD_1927_To_WGS_1984_3"
              },
              {
                "geoTransforms": [
                  {
                    "wkid": 108001,
                    "latestWkid": 1241,
                    "transformForward": true,
                    "name": "NAD_1927_To_NAD_1983_NADCON"
                  },
                  {
                    "wkid": 108190,
                    "latestWkid": 108190,
                    "transformForward": false,
                    "name": "WGS_1984_(ITRF00)_To_NAD_1983"
                  }
                ]
              }
            ]
        """
        params = {IN_SR: inSR,
                  OUT_SR: outSR,
                  EXTENT_OF_INTEREST: extentOfInterest,
                  NUM_OF_RESULTS: numOfResults
                }

        res = POST(self.url + '/findTransformations', params, token=self.token)
        if int(numOfResults) == 1:
            return res[0]
        else:
            return res

    @geometry_passthrough
    def project(self, geometries, inSR, outSR, transformation='', transformForward='false'):
        """project a single or group of geometries

        Required:
            geometries --
            inSR --
            outSR --

        Optional:
            transformation --
            trasnformForward --
        """
        params = {GEOMETRIES: self.validateGeometries(geometries),
                  IN_SR: inSR,
                  OUT_SR: outSR,
                  TRANSFORMATION: transformation,
                  TRANSFORM_FORWARD: transformForward
                }

        gc = GeometryCollection(POST(self.url + '/project', params, token=self.token))
        gc.spatialReference = outSR if outSR else inSR
        return gc

    def __repr__(self):
        try:
            return "<restapi.GeometryService: '{}'>".format(self.url.split('://')[1].split('/')[0])
        except:
            return '<restapi.GeometryService>'

class ImageService(BaseService):
    geometry_service = None

    def adjustbbox(self, boundingBox):
        """method to adjust bounding box for image clipping to maintain
        cell size.

        Required:
            boundingBox -- bounding box string (comma separated)
        """
        cell_size = int(self.pixelSizeX)
        if isinstance(boundingBox, basestring):
            boundingBox = boundingBox.split(',')
        return ','.join(map(str, map(lambda x: Round(x, cell_size), boundingBox)))

    def pointIdentify(self, geometry=None, **kwargs):
        """method to get pixel value from x,y coordinates or JSON point object

        geometry -- input restapi.Geometry() object or point as json

        Recognized key word arguments:
            x -- x coordinate
            y -- y coordinate
            inSR -- input spatial reference.  Should be supplied if spatial
                reference is different from the Image Service's projection

        geometry example:
            geometry = {"x":3.0,"y":5.0,"spatialReference":{"wkid":102100}}
        """
        IDurl = self.url + '/identify'

        if IN_SR in kwargs:
            inSR = kwargs[IN_SR]
        else:
            inSR = self.spatialReference

        if geometry is not None:
            if not isinstance(geometry, Geometry):
                geometry = Geometry(geometry)
            inSR = geometry.spatialReference

        elif GEOMETRY in kwargs:
            g = Geometry(kwargs[GEOMETRY], spatialReference=inSR)
            inSR = g.spatialReference

        elif X in kwargs and Y in kwargs:
            g = {X: kwargs[X], Y: kwargs[Y]}
            if SR in kwargs:
                g[SPATIAL_REFERENCE] = {WKID: kwargs[SR]}
            else:
                g[SPATIAL_REFERENCE] = {WKID: self.spatialReference}
            geometry = Geometry(g)

        else:
            raise ValueError('Not a valid input geometry!')

        params = {
            GEOMETRY: geometry.dumps(),
            IN_SR: inSR,
            GEOMETRY_TYPE: ESRI_POINT,
            F: JSON,
            RETURN_GEOMETRY: FALSE,
            RETURN_CATALOG_ITEMS: FALSE,
        }

        for k,v in kwargs.iteritems():
            if k not in params:
                params[k] = v

        j = POST(IDurl, params, cookies=self._cookie)
        return j.get(VALUE)

    def exportImage(self, poly, out_raster, envelope=False, rendering_rule=None, interp=BILINEAR_INTERPOLATION, nodata=None, **kwargs):
        """method to export an AOI from an Image Service

        Required:
            poly -- polygon features
            out_raster -- output raster image

        Optional:
            envelope -- option to use envelope of polygon
            rendering_rule -- rendering rule to perform raster functions as JSON
            kwargs -- optional key word arguments for other parameters
        """
        if not out_raster.endswith('.tif'):
            out_raster = os.path.splitext(out_raster)[0] + '.tif'
        query_url = '/'.join([self.url, EXPORT_IMAGE])

        if isinstance(poly, Geometry):
            in_geom = poly
        else:
            in_geom = Geometry(poly)

        sr = in_geom.spatialReference

        if envelope:
            geojson = in_geom.envelope()
            geometryType = ESRI_ENVELOPE
        else:
            geojson = in_geom.dumps()
            geometryType = in_geom.geometryType

        if sr != self.spatialReference:
            self.geometry_service = GeometryService()
            gc = self.geometry_service.project(in_geom, in_geom.spatialReference, self.getSR())
            in_geom = gc

        # The adjust aspect ratio doesn't seem to fix the clean pixel issue
        bbox = self.adjustbbox(in_geom.envelope())
        #if not self.compatible_with_version(10.3):
        #    bbox = self.adjustbbox(in_geom.envelope())
        #else:
        #    bbox = in_geom.envelope()

        # imageSR
        if IMAGE_SR not in kwargs:
            imageSR = sr
        else:
            imageSR = kwargs[IMAGE_SR]

        if NO_DATA in kwargs:
            nodata = kwargs[NO_DATA]

        # check for raster function availability
        if not self.allowRasterFunction:
            rendering_rule = None

        # find width and height for image size (round to whole number)
        bbox_int = map(int, map(float, bbox.split(',')))
        width = abs(bbox_int[0] - bbox_int[2])
        height = abs(bbox_int[1] - bbox_int[3])

        matchType = NO_DATA_MATCH_ANY
        if ',' in str(nodata):
            matchType = NO_DATA_MATCH_ALL

        # set params
        p = {F:PJSON,
             RENDERING_RULE: rendering_rule,
             ADJUST_ASPECT_RATIO: TRUE,
             BBOX: bbox,
             FORMAT: TIFF,
             IMAGE_SR: imageSR,
             BBOX_SR: self.spatialReference,
             SIZE: '{0},{1}'.format(width,height),
             PIXEL_TYPE: self.pixelType,
             NO_DATA_INTERPRETATION: '&'.join(map(str, filter(lambda x: x not in (None, ''),
                ['noData=' + str(nodata) if nodata != None else '', 'noDataInterpretation=%s' %matchType if nodata != None else matchType]))),
             INTERPOLATION: interp
            }

        # overwrite with kwargs
        for k,v in kwargs.iteritems():
            if k not in [SIZE, BBOX_SR]:
                p[k] = v

        # post request
        r = POST(query_url, p, cookies=self._cookie)

        if r.get('href', None) is not None:
            tiff = POST(r.get('href').strip(), ret_json=False).content
            with open(out_raster, 'wb') as f:
                f.write(tiff)
            print('Created: "{0}"'.format(out_raster))

    def clip(self, poly, out_raster, envelope=True, imageSR='', noData=None):
        """method to clip a raster"""
        # check for raster function availability
        if not self.allowRasterFunction:
            raise NotImplemented('This Service does not support Raster Functions!')
        if envelope:
            if not isinstance(poly, Geometry):
                poly = Geometry(poly)
            geojson = poly.envelopeAsJSON()
            geojson[SPATIAL_REFERENCE] = poly.json[SPATIAL_REFERENCE]
        else:
            geojson = Geometry(poly).dumps() if not isinstance(poly, Geometry) else poly.dumps()
        ren = {
          "rasterFunction" : "Clip",
          "rasterFunctionArguments" : {
            "ClippingGeometry" : geojson,
            "ClippingType": CLIP_INSIDE,
            },
          "variableName" : "Raster"
        }
        self.exportImage(poly, out_raster, rendering_rule=ren, noData=noData, imageSR=imageSR)

    def arithmetic(self, poly, out_raster, raster_or_constant, operation=RASTER_MULTIPLY, envelope=False, imageSR='', **kwargs):
        """perform arithmetic operations against a raster

        Required:
            poly -- input polygon or JSON polygon object
            out_raster -- full path to output raster
            raster_or_constant -- raster to perform opertion against or constant value

        Optional:
            operation -- arithmetic operation to use, default is multiply (3) all options: (1|2|3)
            envelope -- if true, will use bounding box of input features
            imageSR -- output image spatial reference

        Operations:
            1 -- esriRasterPlus
            2 -- esriRasterMinus
            3 -- esriRasterMultiply
        """
        ren = {
              "rasterFunction" : "Arithmetic",
              "rasterFunctionArguments" : {
                   "Raster" : "$$",
                   "Raster2": raster_or_constant,
                   "Operation" : operation
                 }
              }
        self.exportImage(poly, out_raster, rendering_rule=json.dumps(ren), imageSR=imageSR, **kwargs)

class GPService(BaseService):
    """GP Service object

        Required:
            url -- GP service url

        Optional (below params only required if security is enabled):
            usr -- username credentials for ArcGIS Server
            pw -- password credentials for ArcGIS Server
            token -- token to handle security (alternative to usr and pw)
            proxy -- option to use proxy page to handle security, need to provide
                full path to proxy url.
        """

    def task(self, name):
        """returns a GP Task object"""
        return GPTask('/'.join([self.url, name]))

class GPTask(BaseService):
    """GP Task object

    Required:
        url -- GP Task url

    Optional (below params only required if security is enabled):
        usr -- username credentials for ArcGIS Server
        pw -- password credentials for ArcGIS Server
        token -- token to handle security (alternative to usr and pw)
        proxy -- option to use proxy page to handle security, need to provide
            full path to proxy url.
     """

    @property
    def isSynchronous(self):
        """task is synchronous"""
        return self.executionType == SYNCHRONOUS

    @property
    def isAsynchronous(self):
        """task is asynchronous"""
        return self.executionType == ASYNCHRONOUS

    @property
    def outputParameter(self):
        """returns the first output parameter (if there is one)"""
        try:
            return self.outputParameters[0]
        except IndexError:
            return None

    @property
    def outputParameters(self):
        """returns list of all output parameters"""
        return [p for p in self.parameters if p.direction == OUTPUT_PARAMETER]


    def list_parameters(self):
        """lists the parameter names"""
        return [p.name for p in self.parameters]

    def run(self, params_json={}, outSR='', processSR='', returnZ=False, returnM=False, **kwargs):
        """Runs a Syncrhonous/Asynchronous GP task, automatically uses appropriate option

        Required:
            task -- name of task to run
            params_json -- JSON object with {parameter_name: value, param2: value2, ...}

        Optional:
            outSR -- spatial reference for output geometries
            processSR -- spatial reference used for geometry opterations
            returnZ -- option to return Z values with data if applicable
            returnM -- option to return M values with data if applicable
            kwargs -- keyword arguments, can substitute this to pass in GP params by name instead of
                using the params_json dictionary.  Only valid if params_json dictionary is not supplied.
        """
        if self.isSynchronous:
            runType = EXECUTE
        else:
            runType = SUBMIT_JOB
        gp_exe_url = '/'.join([self.url, runType])
        if not params_json:
            params_json = {}
            for k,v in kwargs.iteritems():
                params_json[k] = v
        params_json['env:outSR'] = outSR
        params_json['env:processSR'] = processSR
        params_json[RETURN_Z] = returnZ
        params_json[RETURN_M] = returnZ
        params_json[F] = JSON
        r = POST(gp_exe_url, params_json, ret_json=False, cookies=self._cookie)
        gp_elapsed = r.elapsed

        # get result object as JSON
        res = r.json()

        # determine if there's an output parameter: if feature set, push result value into defaultValue
        if self.outputParameter and self.outputParameter.dataType == 'GPFeatureRecordSetLayer':
            try:
                default = self.outputParameter.defaultValue
                feature_set = default
                feature_set[FEATURES] = res[RESULTS][0][VALUE][FEATURES]
                feature_set[FIELDS] = default['Fields'] if 'Fields' in default else default[FIELDS]
                res[VALUE] = feature_set
            except:
                pass
        else:
            res[VALUE] = res[RESULTS][0].get(VALUE)

        print('GP Task "{}" completed successfully. (Elapsed time {})'.format(self.name, gp_elapsed))
        return GPResult(res)
