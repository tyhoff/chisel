#!/usr/bin/python
import string
import lldb
import fblldbbase as fb
import fblldbobjcruntimehelpers as runtimeHelpers

def lldbcommands():
  return [
    FBPrintMethods(),
    FBPrintProperties()
  ]

class FBPrintMethods(fb.FBCommand):
  def name(self):
    return 'pmethods'

  def description(self):
    return 'Print the class instance methods.'

  def options(self):
    return [
      fb.FBCommandArgument(short='-a', long='--address', arg='showaddr', help='Print the implementation address of the method', default=False, boolean=True),
      fb.FBCommandArgument(short='-i', long='--instance', arg='insmethod', help='Print the instance methods', default=False, boolean=True),
      fb.FBCommandArgument(short='-c', long='--class', arg='clsmethod', help='Print the class methods', default=False, boolean=True)
    ]

  def args(self):
    return [ fb.FBCommandArgument(arg='class or instance', type='id or Class', help='an Objective-C Class.') ]

  def run(self, arguments, options):
    cls = arguments[0]
    if not isClassObject(cls):
      cls = runtimeHelpers.object_getClass(cls)
      if not isClassObject(cls):
          raise Exception('Invalid argument. Please specify an instance or a Class.')

    if options.clsmethod:
      print 'Class Methods:'
      printClassMethods(cls, options.showaddr)

    if options.insmethod:
      print '\nInstance Methods:'
      printInstanceMethods(cls, options.showaddr)

    if not options.clsmethod and not options.insmethod:
      print 'Class Methods:'
      printClassMethods(cls, options.showaddr)
      print '\nInstance Methods:'
      printInstanceMethods(cls, options.showaddr)


class FBPrintProperties(fb.FBCommand):

  def name(self):
    return 'pproperties'
   
  def description(self):
    return "Print the properties of an instance"

  def options(self):
    return [
      fb.FBCommandArgument(short='-v', long='--value', arg='showvalue', help='Print the value of a property', default=False, boolean=True),
    ]

  def args(self):
    return [ fb.FBCommandArgument(arg='class or instance', type='id or Class', help='an Objective-C Class.') ]

  def run(self, arguments, options):
    cls = runtimeHelpers.object_getClass(arguments[0])
    if not isClassObject(cls):
        raise Exception('Invalid argument. Please specify an instance or a Class.')
    printProperties(cls)

# helpers 
def isClassObject(arg):
  return runtimeHelpers.class_isMetaClass(runtimeHelpers.object_getClass(arg))

def printInstanceMethods(cls, showaddr=False, prefix='-'):
  json_method_array = get_oc_methods_json(cls)
  if json_method_array:
    for m in json_method_array:
      method = Method(m)
      if showaddr:
        print prefix + ' ' + method.prettyPrintString() + ' ' + str(method.imp)
      else:
        print prefix + ' ' + method.prettyPrintString()

def printClassMethods(cls, showaddr=False):
  printInstanceMethods(runtimeHelpers.object_getClass(cls), showaddr, '+')

def printProperties(cls, showvalue=False):
  propsJson = getPropertiesJson(cls)
  if propsJson:
    for m in propsJson:
      prop = Property(m)
      print prop.prettyPrintString()


def decode(code):
  encodeMap = {
    'c': 'char',
    'i': 'int',
    's': 'short',
    'l': 'long',
    'q': 'long long',

    'C': 'unsigned char',
    'I': 'unsigned int',
    'S': 'unsigned short',
    'L': 'unsigned long',
    'Q': 'unsigned long long',

    'f': 'float',
    'd': 'double',
    'B': 'bool',
    'v': 'void',
    '*': 'char *',
    '@': 'id',
    '#': 'Class',
    ':': 'SEL',
  }

  ret = code
  if code in encodeMap:
    ret = encodeMap[code]
  return ret

# Notice that evaluateExpression doesn't work with variable arguments. such as -[NSString stringWithFormat:]
# I remove the "free(methods)" because it would cause evaluateExpressionValue to raise exception some time.
def get_oc_methods_json(klass):
  tmpString = """
    unsigned int outCount;
    Method *methods = (Method *)class_copyMethodList((Class)$cls, &outCount);
    NSMutableArray *result = (id)[NSMutableArray array];
    
    for (int i = 0; i < outCount; i++) {
      NSMutableDictionary *m = (id)[NSMutableDictionary dictionary];

      SEL name = (SEL)method_getName(methods[i]);
      [m setObject:(id)NSStringFromSelector(name) forKey:@"name"];
      
      char * encoding = (char *)method_getTypeEncoding(methods[i]);
      [m setObject:(id)[NSString stringWithUTF8String:encoding] forKey:@"type_encoding"];
      
      NSMutableArray *types = (id)[NSMutableArray array];
      NSInteger args = (NSInteger)method_getNumberOfArguments(methods[i]);
      for (int idx = 0; idx < args; idx++) {
          char *type = (char *)method_copyArgumentType(methods[i], idx);
          [types addObject:(id)[NSString stringWithUTF8String:type]];
      }
      [m setObject:types forKey:@"parameters_type"];
      
      char *ret_type = (char *)method_copyReturnType(methods[i]);
      [m setObject:(id)[NSString stringWithUTF8String:ret_type] forKey:@"return_type"];
      
      long imp = (long)method_getImplementation(methods[i]);
      [m setObject:[NSNumber numberWithLongLong:imp] forKey:@"implementation"];
      
      [result addObject:m];
    }
    RETURN(result);
  """
  command = string.Template(tmpString).substitute(cls=klass)
  return fb.evaluate(command)


class Method:

  def __init__(self, json):
    self.name = json['name']
    self.type_encoding = json['type_encoding']
    self.parameters_type = json['parameters_type']
    self.return_type = json['return_type']
    self.imp = self.toHex(json['implementation'])

  def prettyPrintString(self):
    argnum = len(self.parameters_type)
    names = self.name.split(':')

    # the argnum count must be bigger then 2, index 0 for self, index 1 for SEL
    for i in range(2, argnum):
      arg_type = self.parameters_type[i]
      names[i-2] = names[i-2] + ":(" +  decode(arg_type) + ")arg" + str(i-2)

    string = " ".join(names)
    return "({}){}".format(decode(self.return_type), string)

  def toHex(self, addr):
    return hex(addr)

  def __str__(self):
    return "<Method:" + self.oc_method + "> " + self.name + " --- " + self.type + " --- " + self.imp

def getPropertiesJson(klass):
  tmpString = """
      NSMutableArray *result = (id)[NSMutableArray array];
      unsigned int count;
      objc_property_t *props = (objc_property_t *)class_copyPropertyList([self class], &count);
      for (int i = 0; i < count; i++) {
          NSMutableDictionary *dict = (id)[NSMutableDictionary dictionary];
          
          char *name = (char *)property_getName(props[i]);
          [dict setObject:(id)[NSString stringWithUTF8String:name] forKey:@"name"];
          
          char *attrstr = (char *)property_getAttributes(props[i]);
          [dict setObject:(id)[NSString stringWithUTF8String:attrstr] forKey:@"attributes_string"];
          
          NSMutableDictionary *attrsDict = (id)[NSMutableDictionary dictionary];
          unsigned int pcount;
          objc_property_attribute_t *attrs = (objc_property_attribute_t *)property_copyAttributeList(props[i], &pcount);
          for (int i = 0; i < pcount; i++) {
              NSString *name = (id)[NSString stringWithUTF8String:(char *)attrs[i].name];
              NSString *value = (id)[NSString stringWithUTF8String:(char *)attrs[i].value];
              [attrsDict setObject:value forKey:name];
          }
          [dict setObject:attrsDict forKey:@"attributes"];
          
          [result addObject:dict];
      }
      RETURN(result);
    """
  command = string.Template(tmpString).substitute(cls=klass)
  return fb.evaluate(command)

class Property:

  def __init__(self, json):
    self.name = json['name']
    self.attributes_string = json['attributes_string']
    self.attributes = json['attributes']

  def prettyPrintString(self):
    attrs = []
    if self.attributes.has_key('N'):
      attrs.append('nonatomic')
    else:
      attrs.append('atomic')

    if self.attributes.has_key('&'):
      attrs.append('strong')
    elif self.attributes.has_key('C'):
      attrs.append('copy')
    elif self.attributes.has_key('W'):
      attrs.append('weak')
    else:
      attrs.append('assign')

    if self.attributes.has_key('R'):
      attrs.append('readonly')

    if self.attributes.has_key('G'):
      attrs.append("getter={}".format(self.attributes['G']))
    if self.attributes.has_key('S'):
      attrs.append("setter={}".format(self.attributes['S']))

    return "@property ({}) {} {}".format(", ".join(attrs), decode(self.attributes['T']), self.name)
